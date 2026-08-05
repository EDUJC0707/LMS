"""로그인 시도 제한 — 표적 공격을 전제로 한다(2026-08-05 사용자: *"other teachers
might want to hack"*).

우리 아이디는 **추측 가능하다** — `{이름}{번호4자리}`, 학부모는 `{자녀아이디}p`.
학생 이름만 알면 아이디의 대부분이 나온다. 그러니 여기서 막아야 하는 것은 무작위
스캔이 아니라 **특정 계정을 노린 사람**이다.

그래서 한도가 둘이다:
  - **계정별** — 표적이 된 계정을 지킨다. 공격자가 IP 를 바꿔도 따라간다(이쪽이 본체)
  - **IP별** — 한 곳에서 여러 계정을 훑는 것을 잡는다(보조)

**영구 잠금은 두지 않는다.** 잠금은 무기가 된다 — 경쟁 학원이 시험 전날 학생들
아이디로 일부러 실패시키면 그게 곧 서비스 거부다. 시간이 지나면 저절로 풀린다.
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from .models import LoginAttempt, User
from .throttling import ACCOUNT_MAX_FAILURES, FAILURE_WINDOW, IP_MAX_FAILURES

PASSWORD = "pw-Secret-77!"


def make_user(login_id, role=User.Role.STUDENT, name="사용자"):
    return User.objects.create_user(
        login_id=login_id, password=PASSWORD, name=name, role=role
    )


class LoginThrottleTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def login(self, login_id, password=PASSWORD, ip="203.0.113.9"):
        return self.client.post(
            "/api/auth/login",
            {"login_id": login_id, "password": password},
            format="json",
            REMOTE_ADDR=ip,
        )

    def burn_account_budget(self, login_id, ip="203.0.113.9"):
        """계정 한도를 정확히 소진시킨다(아직 차단은 아닌 상태)."""
        for _ in range(ACCOUNT_MAX_FAILURES):
            response = self.login(login_id, password="wrong", ip=ip)
            self.assertEqual(response.status_code, 401)

    def test_failures_beyond_the_budget_are_blocked(self):
        make_user("김하늘0001")
        self.burn_account_budget("김하늘0001")
        self.assertEqual(self.login("김하늘0001", password="wrong").status_code, 429)

    def test_correct_password_is_refused_once_the_budget_is_spent(self):
        # 핵심이다. 검사가 authenticate **뒤**에 있으면, 여섯 번째에 비밀번호를
        # 맞힌 공격자는 그대로 들어온다 — 제한이 있으나 마나가 된다.
        make_user("김하늘0001")
        self.burn_account_budget("김하늘0001")
        response = self.login("김하늘0001")  # 진짜 비밀번호
        self.assertEqual(response.status_code, 429)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_successful_logins_do_not_spend_the_budget(self):
        # 매일 로그인하는 학생이 제 발로 잠기면 안 된다 — 실패만 센다.
        make_user("김하늘0001")
        for _ in range(ACCOUNT_MAX_FAILURES + 3):
            self.assertEqual(self.login("김하늘0001").status_code, 200)
        self.assertEqual(self.login("김하늘0001", password="wrong").status_code, 401)

    def test_one_account_lockout_does_not_touch_another(self):
        make_user("김하늘0001")
        make_user("강태윤0026")
        self.burn_account_budget("김하늘0001")
        self.assertEqual(self.login("김하늘0001", password="wrong").status_code, 429)
        self.assertEqual(self.login("강태윤0026").status_code, 200)

    def test_failures_outside_the_window_no_longer_count(self):
        # 영구 잠금이 아니다 — 창이 지나면 저절로 풀린다.
        make_user("김하늘0001")
        self.burn_account_budget("김하늘0001")
        expired = timezone.now() - FAILURE_WINDOW - timedelta(seconds=1)
        LoginAttempt.objects.update(created_at=expired)
        self.assertEqual(self.login("김하늘0001").status_code, 200)

    def test_unknown_login_id_is_throttled_the_same_way(self):
        # 없는 계정만 다르게 굴면 그 차이로 계정 존재 여부가 새어 나간다.
        self.burn_account_budget("없는아이디9999")
        self.assertEqual(self.login("없는아이디9999", password="wrong").status_code, 429)

    def test_one_ip_sweeping_many_accounts_gets_blocked(self):
        # 계정별 한도만 있으면 공격자는 계정을 바꿔 가며 계속 두드릴 수 있다.
        attacker = "198.51.100.7"
        for index in range(IP_MAX_FAILURES):
            self.login(f"표적{index:04d}", password="wrong", ip=attacker)
        make_user("김하늘0001")
        self.assertEqual(
            self.login("김하늘0001", password="wrong", ip=attacker).status_code, 429
        )

    def test_a_different_ip_is_unaffected_by_the_sweep(self):
        # 학원 와이파이가 공용 IP 라 남의 실패로 학생이 잠기면 안 된다 —
        # 그래서 IP 한도는 넉넉하고, 진짜 방어선은 계정별 한도다.
        attacker = "198.51.100.7"
        for index in range(IP_MAX_FAILURES):
            self.login(f"표적{index:04d}", password="wrong", ip=attacker)
        make_user("김하늘0001")
        self.assertEqual(self.login("김하늘0001", ip="203.0.113.9").status_code, 200)

    def test_admin_login_is_protected_too(self):
        # 대표 계정이야말로 표적이다. 경로가 다르다고 빠지면 안 된다.
        make_user("한종철0001", role=User.Role.OWNER, name="한종철")
        for _ in range(ACCOUNT_MAX_FAILURES):
            self.client.post(
                "/api/auth/login/admin",
                {"login_id": "한종철0001", "password": "wrong"},
                format="json",
                REMOTE_ADDR="203.0.113.9",
            )
        response = self.client.post(
            "/api/auth/login/admin",
            {"login_id": "한종철0001", "password": PASSWORD},
            format="json",
            REMOTE_ADDR="203.0.113.9",
        )
        self.assertEqual(response.status_code, 429)

    def test_client_ip_comes_from_the_proxy_header(self):
        # Fly 뒤에서는 REMOTE_ADDR 이 프록시다. 그걸 그대로 쓰면 **모든 사용자가
        # 한 IP** 로 묶여 IP 한도가 전체를 잠근다.
        for index in range(IP_MAX_FAILURES):
            self.client.post(
                "/api/auth/login",
                {"login_id": f"표적{index:04d}", "password": "wrong"},
                format="json",
                REMOTE_ADDR="10.0.0.1",
                HTTP_X_FORWARDED_FOR="198.51.100.7",
            )
        make_user("김하늘0001")
        blocked = self.client.post(
            "/api/auth/login",
            {"login_id": "김하늘0001", "password": PASSWORD},
            format="json",
            REMOTE_ADDR="10.0.0.1",
            HTTP_X_FORWARDED_FOR="198.51.100.7",
        )
        self.assertEqual(blocked.status_code, 429)
        allowed = self.client.post(
            "/api/auth/login",
            {"login_id": "김하늘0001", "password": PASSWORD},
            format="json",
            REMOTE_ADDR="10.0.0.1",
            HTTP_X_FORWARDED_FOR="203.0.113.9",
        )
        self.assertEqual(allowed.status_code, 200)

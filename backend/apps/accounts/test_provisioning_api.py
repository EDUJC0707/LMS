"""계정 일괄 발급·등록 전환 API 8차 슬라이스 테스트 — PRD 3.1.5·8-3·8-4.

검증 축:
- 기능 게이트: 계정관리 키(FeatureRequired) — 조교 프리셋에 없어 403,
  delta 부여 시 허용
- 일괄 발급: 학생 User(아이디={이름}{뒷4자리}·랜덤 비번·must_change_password) +
  Student(예비등록) / parent_phone → 학부모 계정 생성(아이디=**학생 아이디+p**)·
  **중복 전화면 기존 학부모에 자녀 연결만**(ParentStudent) / **무전화 학생은
  학부모 번호 뒷4자리**(8-4 개정) / 동명이인+같은 뒷4자리는 **접미사로 해소** /
  아이디를 만들 수 없는 행(이름·번호 불량)은 **해당 행만 실패**(행 단위
  savepoint — 성공 행은 유지) / 초기 비밀번호는 응답 반환·credentials_sent_at 미스탬프
- 원번(2026-07-29 재개정): 입력이 아니라 **(이름, 휴대폰) 파생값** — 손입력
  원번은 거절, **학년은 원번에 관여하지 않는다**(없거나 못 읽어도 발급된다),
  동명이인+같은 뒷4자리 두 명은 둘 다 생성되고 **원번이 같다**(단독 UNIQUE 아님)
- 등록 전환: 예비등록→등록 + registered_at (그 외 상태 400)
"""
import json

from django.test import TestCase

from .features import FeatureKey
from .models import Parent, ParentStudent, StaffFeatureGrant, Student, User

PASSWORD = "pw-Secret-77!"
BULK_URL = "/api/admin/accounts/bulk"


def make_user(login_id, role, name="사용자", **extra):
    return User.objects.create_user(
        login_id=login_id, password=PASSWORD, name=name, role=role, **extra
    )


class ProvisioningFixtureMixin:
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user("pv-own", User.Role.OWNER, name="대표")
        cls.admin = make_user("pv-adm", User.Role.ADMIN, name="관리자")
        cls.assistant = make_user("pv-ast", User.Role.ASSISTANT, name="조교")

    def post_bulk(self, rows, user=None):
        self.client.force_login(user or self.admin)
        return self.client.post(
            BULK_URL, data=json.dumps(rows), content_type="application/json"
        )


class BulkFeatureGateTests(ProvisioningFixtureMixin, TestCase):
    """계정관리 기능 키 게이트 — 프리셋 ⊕ delta."""

    def test_assistant_without_feature_gets_403(self):
        self.assertEqual(self.post_bulk([], user=self.assistant).status_code, 403)

    def test_assistant_with_delta_passes_gate(self):
        StaffFeatureGrant.objects.create(
            user=self.assistant,
            feature_key=FeatureKey.ACCOUNT_ADMIN,
            is_granted=True,
            granted_by=self.owner,
        )
        # 게이트는 통과하고 빈 명단 검증(400)까지 도달한다.
        self.assertEqual(self.post_bulk([], user=self.assistant).status_code, 400)

    def test_student_role_gets_403(self):
        student_user = make_user("pv-stu", User.Role.STUDENT)
        self.assertEqual(self.post_bulk([], user=student_user).status_code, 403)


class BulkIssueTests(ProvisioningFixtureMixin, TestCase):
    """POST /api/admin/accounts/bulk — 생성·연결·행 단위 실패."""

    def test_creates_student_and_parent_accounts(self):
        rows = [
            {
                "name": "김학생",
                "phone": "01011112222",
                "parent_phone": "01033334444",
                "grade": "고3",
                "school": "한종철고",
            }
        ]
        res = self.post_bulk(rows)
        self.assertEqual(res.status_code, 200)
        body = res.json()
        result = body["results"][0]
        self.assertEqual(result["status"], "생성")
        self.assertEqual(result["login_id"], "김학생2222")

        student_user = User.objects.get(login_id="김학생2222")
        self.assertEqual(student_user.role, User.Role.STUDENT)
        self.assertEqual(student_user.name, "김학생")
        self.assertEqual(student_user.phone, "01011112222")  # 연락처는 그대로 보존
        self.assertTrue(student_user.must_change_password)
        self.assertTrue(student_user.check_password(result["initial_password"]))

        student = Student.objects.get(user=student_user)
        self.assertEqual(student.enrollment_status, Student.EnrollmentStatus.PRE_REGISTERED)
        # 원번은 파생값 — 이름 + 뒷4자리. 응답에도 실려 나간다
        # (관리자가 OMR 답안지에 적을 값이라 발급 시점에 보여야 한다).
        self.assertEqual(student.matching_key, "김학생2222")
        self.assertEqual(result["matching_key"], "김학생2222")
        self.assertEqual(student.grade, "고3")
        self.assertEqual(student.school, "한종철고")
        self.assertIsNone(student.credentials_sent_at)  # 발송은 알림톡 연동 대기

        parent = Parent.objects.get(phone="01033334444")
        self.assertIsNotNone(parent.user)
        self.assertEqual(parent.user.role, User.Role.PARENT)
        # 학부모 아이디 = 학생 아이디 + p (학부모 번호와 무관)
        self.assertEqual(parent.user.login_id, "김학생2222p")
        self.assertEqual(result["parent"]["login_id"], "김학생2222p")
        self.assertEqual(parent.user.phone, "01033334444")
        self.assertIsNone(parent.credentials_sent_at)
        self.assertTrue(result["parent"]["created"])
        self.assertTrue(parent.user.check_password(result["parent"]["initial_password"]))
        self.assertTrue(
            ParentStudent.objects.filter(parent=parent, student=student).exists()
        )

    def test_duplicate_parent_phone_links_to_existing_parent(self):
        rows = [
            {
                "name": "김첫째", "phone": "01011110001",
                "parent_phone": "01099998888", "grade": "고2",
            },
            {
                "name": "김둘째", "phone": "01011110002",
                "parent_phone": "01099998888", "grade": "고1",
            },
        ]
        res = self.post_bulk(rows)
        body = res.json()
        self.assertEqual(Parent.objects.filter(phone="01099998888").count(), 1)
        parent = Parent.objects.get(phone="01099998888")
        self.assertEqual(ParentStudent.objects.filter(parent=parent).count(), 2)
        self.assertTrue(body["results"][0]["parent"]["created"])
        self.assertFalse(body["results"][1]["parent"]["created"])
        self.assertNotIn("initial_password", body["results"][1]["parent"])
        # 다자녀 학부모 아이디는 **최초 연결 자녀** 기준으로 고정된다(login_id 모듈 계약)
        self.assertEqual(parent.user.login_id, "김첫째0001p")
        self.assertEqual(body["results"][1]["parent"]["login_id"], "김첫째0001p")

    def test_existing_parent_in_db_gets_link_only(self):
        existing = Parent.objects.create(
            user=make_user("기존학부모0000p", User.Role.PARENT, name="기존학부모"),
            phone="01055550000",
        )
        res = self.post_bulk(
            [{
                "name": "신규생", "phone": "01055551111",
                "parent_phone": "01055550000", "grade": "고2",
            }]
        )
        body = res.json()
        self.assertFalse(body["results"][0]["parent"]["created"])
        self.assertEqual(Parent.objects.filter(phone="01055550000").count(), 1)
        student = Student.objects.get(user__login_id="신규생1111")
        self.assertTrue(
            ParentStudent.objects.filter(parent=existing, student=student).exists()
        )

    def test_phoneless_student_uses_parent_phone_tail(self):
        # 무전화 학생 — 학부모 번호 뒷4자리를 쓰고, 학부모는 그 아이디 + p
        res = self.post_bulk(
            [{"name": "무폰생", "parent_phone": "01077774821", "grade": "고2"}]
        )
        body = res.json()
        self.assertEqual(body["results"][0]["login_id"], "무폰생4821")
        self.assertEqual(body["results"][0]["parent"]["login_id"], "무폰생4821p")
        # 원번도 같은 뒷자리 규칙을 쓴다(학부모 번호 뒷4자리)
        self.assertEqual(body["results"][0]["matching_key"], "무폰생4821")
        self.assertTrue(User.objects.filter(login_id="무폰생4821").exists())
        self.assertTrue(
            User.objects.filter(login_id="무폰생4821p", role=User.Role.PARENT).exists()
        )

    def test_same_name_and_tail_gets_suffix(self):
        # 동명이인 + 같은 뒷4자리 — 실패가 아니라 접미사로 해소, 학부모도 따라간다
        rows = [
            {
                "name": "김민준", "phone": "01011111234",
                "parent_phone": "01055551111", "grade": "고2",
            },
            {
                "name": "김민준", "phone": "01022221234",
                "parent_phone": "01055552222", "grade": "고2",
            },
        ]
        res = self.post_bulk(rows)
        body = res.json()
        self.assertEqual(body["results"][0]["login_id"], "김민준1234")
        self.assertEqual(body["results"][1]["login_id"], "김민준1234a")
        self.assertEqual(body["results"][0]["parent"]["login_id"], "김민준1234p")
        self.assertEqual(body["results"][1]["parent"]["login_id"], "김민준1234ap")
        self.assertEqual(body["summary"]["created"], 2)

    def test_same_name_and_tail_share_one_matching_key(self):
        """원번은 **단독 UNIQUE 가 아니다** — 같은 이름·뒷4자리 두 명이 성립한다.

        아이디는 접미사로 갈라지지만(위 테스트) 원번은 갈리지 않는다. 겹치면
        지면 매칭에서 중복으로 떨어지고 관리자가 고른다(2026-07-29 확정).
        """
        rows = [
            {"name": "김민준", "phone": "01011111234", "grade": "고2"},
            {"name": "김민준", "phone": "01022221234", "grade": "고2"},
        ]
        res = self.post_bulk(rows)
        body = res.json()
        self.assertEqual(body["summary"]["created"], 2)
        self.assertEqual(
            [row["matching_key"] for row in body["results"]], ["김민준1234", "김민준1234"]
        )
        self.assertEqual(Student.objects.filter(matching_key="김민준1234").count(), 2)

    def test_grade_is_not_part_of_the_matching_key(self):
        """학년이 달라도 이름·뒷4자리가 같으면 원번이 같다(2026-07-29 재개정)."""
        rows = [
            {"name": "동명이", "phone": "01011110001", "grade": "고1"},
            {"name": "동명이", "phone": "01022220001", "grade": "고3"},
        ]
        body = self.post_bulk(rows).json()
        self.assertEqual(body["results"][0]["matching_key"], "동명이0001")
        self.assertEqual(body["results"][1]["matching_key"], "동명이0001")

    def test_supplied_matching_key_rejected(self):
        """손입력 원번은 **행 실패**다 — 무시하면 준 값이 저장됐다고 오해한다.

        원번이 파생값이 된 뒤 입력칸은 사라졌다(AccountsPage). 옛 서식이 그대로
        들어오면 조용히 다른 값이 저장되는 대신 그 행만 사유와 함께 실패한다.
        """
        rows = [
            {
                "name": "손입력", "phone": "01011110001",
                "grade": "고2", "matching_key": "26901",
            },
            {"name": "정상생", "phone": "01011110002", "grade": "고2"},
        ]
        body = self.post_bulk(rows).json()
        self.assertEqual(body["results"][0]["status"], "실패")
        self.assertIn("원번", body["results"][0]["error"])
        self.assertFalse(User.objects.filter(name="손입력").exists())
        self.assertEqual(body["results"][1]["status"], "생성")
        self.assertEqual(body["summary"], {
            "created": 1, "failed": 1, "parents_created": 0, "parents_linked": 0
        })

    def test_row_without_grade_is_issued(self):
        """학년이 비어도 발급된다 — 원번의 재료가 아니게 됐다(2026-07-29 재개정).

        학년은 학생 정보로 계속 쓰지만(승급·명단) 계정 발급을 막을 이유가 없다.
        비면 그대로 빈 문자열로 저장되고 승급 커맨드가 건너뛰며 드러난다.
        """
        body = self.post_bulk([{"name": "무학년", "phone": "01011110001"}]).json()
        self.assertEqual(body["results"][0]["status"], "생성")
        self.assertEqual(body["results"][0]["matching_key"], "무학년0001")
        self.assertEqual(Student.objects.get(user__name="무학년").grade, "")

    def test_free_form_grade_is_stored_as_is(self):
        """학년 표기는 원번에 관여하지 않으므로 파싱하지 않는다 — 적힌 대로 저장."""
        body = self.post_bulk(
            [
                {"name": "엔수생", "phone": "01011110001", "grade": "N수"},
                {"name": "미상생", "phone": "01011110002", "grade": "고등부"},
            ]
        ).json()
        self.assertEqual(
            [row["status"] for row in body["results"]], ["생성", "생성"]
        )
        self.assertEqual(body["results"][0]["matching_key"], "엔수생0001")
        self.assertEqual(Student.objects.get(user__name="미상생").grade, "고등부")

    def test_name_with_spaces_normalized(self):
        res = self.post_bulk(
            [{"name": " 김 하늘 ", "phone": "010-1111-4821", "grade": "고2"}]
        )
        self.assertEqual(res.json()["results"][0]["login_id"], "김하늘4821")

    def test_unusable_name_fails_only_that_row(self):
        rows = [
            {"name": "!!!", "phone": "01088880000", "grade": "고2"},
            {"name": "정상생", "phone": "01088880001", "grade": "고2"},
        ]
        res = self.post_bulk(rows)
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["results"][0]["status"], "실패")
        self.assertTrue(body["results"][0]["error"])
        self.assertEqual(body["results"][1]["status"], "생성")
        # 실패 행 잔재 없음(행 단위 savepoint 롤백) — 성공 행은 유지.
        self.assertFalse(Student.objects.filter(user__phone="01088880000").exists())
        self.assertTrue(Student.objects.filter(user__login_id="정상생0001").exists())
        self.assertEqual(body["summary"]["created"], 1)
        self.assertEqual(body["summary"]["failed"], 1)

    def test_row_without_any_phone_fails_that_row(self):
        res = self.post_bulk([{"name": "무연락생", "grade": "고2"}])
        body = res.json()
        self.assertEqual(body["results"][0]["status"], "실패")

    def test_row_with_short_phone_fails_that_row(self):
        res = self.post_bulk([{"name": "짧은번호", "phone": "12", "grade": "고2"}])
        body = res.json()
        self.assertEqual(body["results"][0]["status"], "실패")
        self.assertFalse(User.objects.filter(name="짧은번호").exists())

    def test_row_without_name_fails_that_row(self):
        res = self.post_bulk([{"phone": "01012340000", "grade": "고2"}])
        body = res.json()
        self.assertEqual(body["results"][0]["status"], "실패")
        self.assertFalse(User.objects.filter(phone="01012340000").exists())

    def test_non_list_or_empty_body_rejected(self):
        self.assertEqual(self.post_bulk({"name": "딕셔너리"}).status_code, 400)
        self.assertEqual(self.post_bulk([]).status_code, 400)


class RegisterTests(ProvisioningFixtureMixin, TestCase):
    """POST /api/admin/accounts/{student_id}/register — 예비등록→등록."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.student = Student.objects.create(
            user=make_user("rg-stu", User.Role.STUDENT, name="예비생"),
            matching_key="예비생0001",
        )

    def register(self, student_id, user=None):
        self.client.force_login(user or self.admin)
        return self.client.post(f"/api/admin/accounts/{student_id}/register")

    def test_registers_pre_registered_student(self):
        res = self.register(self.student.student_id)
        self.assertEqual(res.status_code, 200)
        self.student.refresh_from_db()
        self.assertEqual(self.student.enrollment_status, Student.EnrollmentStatus.REGISTERED)
        self.assertIsNotNone(self.student.registered_at)
        self.assertEqual(res.json()["enrollment_status"], "등록")

    def test_already_registered_rejected(self):
        self.register(self.student.student_id)
        self.assertEqual(self.register(self.student.student_id).status_code, 400)

    def test_withdrawn_rejected(self):
        self.student.enrollment_status = Student.EnrollmentStatus.WITHDRAWN
        self.student.save(update_fields=["enrollment_status"])
        self.assertEqual(self.register(self.student.student_id).status_code, 400)

    def test_unknown_student_404(self):
        self.assertEqual(self.register(999999).status_code, 404)

    def test_assistant_without_feature_gets_403(self):
        self.assertEqual(
            self.register(self.student.student_id, user=self.assistant).status_code, 403
        )

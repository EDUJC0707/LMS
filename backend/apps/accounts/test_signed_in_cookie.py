"""랜딩이 읽는 로그인 표시 쿠키 (views.SIGNED_IN_COOKIE).

이 쿠키 하나로 `hjcedu.com` 이 방문자를 LMS 로 넘길지 정한다. 그래서 확인할 것은
"켜지는가"가 아니라 **세션과 어긋나지 않는가** 다:

- **JS 가 읽을 수 있어야 한다** — 못 읽으면 랜딩이 판단할 수단이 없어 기능 자체가
  성립하지 않는다. 세션 쿠키를 `HttpOnly` 로 두는 것과 정반대의 요구다.
- **수명이 세션과 같아야 한다** — 표시가 더 오래 살면 세션이 죽은 사람을 LMS 로
  보내고 거기서 로그인 화면이 뜬다. 사용자에겐 원인 모를 튕김이다.
- **로그아웃에 지워져야 한다** — 남으면 로그아웃한 사람이 랜딩을 볼 수 없다.
- **도메인이 세션과 같아야 한다** — 다르면 랜딩(다른 서브도메인)이 못 읽는다.
"""
from django.test import TestCase, override_settings

from .models import User
from .views import SIGNED_IN_COOKIE


class SignedInCookieTests(TestCase):
    def setUp(self):
        self.password = "test1234"
        self.user = User.objects.create_user(
            login_id="김하늘0001",
            password=self.password,
            role=User.Role.STUDENT,
        )

    def _login(self):
        return self.client.post(
            "/api/auth/login",
            {"login_id": self.user.login_id, "password": self.password},
            content_type="application/json",
        )

    def test_login_sets_the_marker(self):
        response = self._login()
        self.assertEqual(response.status_code, 200)
        self.assertIn(SIGNED_IN_COOKIE, response.cookies)

    def test_marker_is_readable_by_javascript(self):
        """`HttpOnly` 면 랜딩이 못 읽는다 — 그러면 이 기능이 통째로 죽는다."""
        cookie = self._login().cookies[SIGNED_IN_COOKIE]
        self.assertFalse(cookie["httponly"])

    def test_marker_outlives_nothing_longer_than_the_session(self):
        """표시가 세션보다 오래 살면 죽은 세션으로 LMS 에 보내게 된다."""
        from django.conf import settings

        cookie = self._login().cookies[SIGNED_IN_COOKIE]
        self.assertEqual(int(cookie["max-age"]), settings.SESSION_COOKIE_AGE)

    def test_logout_clears_the_marker(self):
        self._login()
        response = self.client.post("/api/auth/logout")
        self.assertEqual(response.status_code, 200)
        # 삭제는 빈 값 + 만료로 표현된다.
        self.assertEqual(response.cookies[SIGNED_IN_COOKIE].value, "")

    def test_failed_login_leaves_no_marker(self):
        """비밀번호가 틀렸는데 표시가 켜지면 랜딩이 남을 LMS 로 보낸다."""
        response = self.client.post(
            "/api/auth/login",
            {"login_id": self.user.login_id, "password": "wrong"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)
        self.assertNotIn(SIGNED_IN_COOKIE, response.cookies)

    @override_settings(SESSION_COOKIE_DOMAIN=".hjcedu.com")
    def test_marker_shares_the_session_domain(self):
        """도메인이 다르면 랜딩(다른 서브도메인)이 이 쿠키를 못 본다."""
        cookie = self._login().cookies[SIGNED_IN_COOKIE]
        self.assertEqual(cookie["domain"], ".hjcedu.com")

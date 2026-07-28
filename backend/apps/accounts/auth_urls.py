"""인증·자격 라우트 — /api/ 바로 아래에 마운트된다(config.urls 참조).

- /api/auth/*  로그인 2종·로그아웃·비밀번호 변경·CSRF (PRD §4)
- /api/me      상태 기반 노출의 관문(별도 뷰, 후속 슬라이스에서 확장)

로그인 진입점(2026-07-28 개편): 소비자 통합(`auth/login` — 학생·학부모 공용,
역할은 서버가 users.role 로 판정) + 직원 분리(`auth/login/admin` — 화면 미노출).
구 `auth/login/student`·`auth/login/parent` 는 제거됐다(호환 유지 없음).

도메인 리소스 라우터(/api/accounts/*)는 urls.py 가 담당 — 여기와 섞지 않는다.
"""
from django.urls import path

from . import views

app_name = "auth"

urlpatterns = [
    path("auth/login", views.ConsumerLoginView.as_view(), name="login"),
    path("auth/login/admin", views.AdminLoginView.as_view(), name="login-admin"),
    path("auth/logout", views.LogoutView.as_view(), name="logout"),
    path("auth/password", views.PasswordChangeView.as_view(), name="password-change"),
    path("auth/csrf", views.CsrfCookieView.as_view(), name="csrf"),
    path("me", views.MeView.as_view(), name="me"),
]

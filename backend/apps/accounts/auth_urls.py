"""인증·자격 라우트 — /api/ 바로 아래에 마운트된다(config.urls 참조).

- /api/auth/*  로그인 3종·로그아웃·비밀번호 변경·CSRF (PRD §4 로그인 분리)
- /api/me      상태 기반 노출의 관문(별도 뷰, 후속 슬라이스에서 확장)

도메인 리소스 라우터(/api/accounts/*)는 urls.py 가 담당 — 여기와 섞지 않는다.
"""
from django.urls import path

from . import views

app_name = "auth"

urlpatterns = [
    path("auth/login/student", views.StudentLoginView.as_view(), name="login-student"),
    path("auth/login/parent", views.ParentLoginView.as_view(), name="login-parent"),
    path("auth/login/admin", views.AdminLoginView.as_view(), name="login-admin"),
    path("auth/logout", views.LogoutView.as_view(), name="logout"),
    path("auth/password", views.PasswordChangeView.as_view(), name="password-change"),
    path("auth/csrf", views.CsrfCookieView.as_view(), name="csrf"),
    path("me", views.MeView.as_view(), name="me"),
]

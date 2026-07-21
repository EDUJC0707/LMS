"""개발 설정 — 로컬. runserver + docker-compose(PG·Redis) 전제."""
from .base import *  # noqa: F401,F403
from .base import REST_FRAMEWORK

DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "0.0.0.0"]

# 개발 편의: 인증 없이 API 열람 허용(운영은 base 의 IsAuthenticated 유지).
REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
}

# 이메일은 콘솔로 출력(실발송 없음).
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

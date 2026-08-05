"""운영 설정 — Fly.io. 보안 강화 + Sentry. 비밀은 env(fly secrets)로 주입."""
from config.observability import init_sentry

from .base import *  # noqa: F401,F403
from .base import env

DEBUG = False

# Fly 프록시 뒤 HTTPS 인식
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default=True)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
SECURE_HSTS_INCLUDE_SUBDOMAINS = True

# 프런트 도메인 등 CSRF 신뢰 오리진(env: 콤마구분)
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])

# Sentry — DSN 이 있으면 활성화. 무엇을 보내고 무엇을 막는지는 config/observability.py.
SENTRY_DSN = env("SENTRY_DSN", default="")
# 어느 배포에서 난 에러인지. 이미지 빌드가 넣어 준다(infra/Dockerfile 의 GIT_SHA).
# SDK 가 이 환경변수를 스스로 읽기도 하지만, 그 동작은 코드에서 안 보이고 SDK 판올림에
# 딸려 바뀔 수 있어 명시적으로 넘긴다.
SENTRY_ENABLED = init_sentry(SENTRY_DSN, release=env("SENTRY_RELEASE", default=""))

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
SENTRY_ENABLED = init_sentry(SENTRY_DSN)

# 알림 채널 — 실업체(알리고, docs/decisions.md §3-1). 자격증명은 fly secrets 로
# 주입하고, 비어 있으면 발송이 "API 키가 설정되지 않았습니다" 로 실패한다
# (조용한 성공 없음). 앱푸시는 아직 어댑터가 없다 — 구현체가 생길 때 한 줄 추가한다.
_ALIGO = "apps.notifications.aligo.AligoAdapter"
NOTIFICATION_CHANNEL_BACKENDS = {
    "카카오알림톡": _ALIGO,
    "문자": _ALIGO,
}

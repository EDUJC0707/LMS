"""운영 설정 — Fly.io. 보안 강화 + Sentry. 비밀은 env(fly secrets)로 주입."""
from django.core.exceptions import ImproperlyConfigured

from config.observability import init_sentry

from .base import *  # noqa: F401,F403
from .base import env

DEBUG = False

# --- 오브젝트 스토리지는 운영에서 **필수** --------------------------------
# 버킷이 비면 base 가 파일시스템으로 떨어지고, Fly 컨테이너 디스크는 **재배포마다
# 사라진다.** 그러면 OMR 스캔과 워크북 사진이 조용히 날아가고 재판독도 못 한다.
# 조용히 도는 것보다 안 뜨는 편이 낫다 — 그때는 아직 아무것도 안 잃었다.
# **base 가 읽는 것과 같은 이름을 본다.** Tigris 가 꽂아 주는 이름은 `BUCKET_NAME`,
# django-storages 가 읽는 이름은 `AWS_STORAGE_BUCKET_NAME` 이라 한쪽만 보면
# 스토리지가 멀쩡히 붙어 있는데도 배포가 막힌다(2026-08-12 실제로 막혔다).
# env 를 직접 읽는다 — `from .base import *` 는 캐시된 모듈 값을 가져오므로
# import 순서에 결과가 매인다.
if not (env("BUCKET_NAME", default="") or env("AWS_STORAGE_BUCKET_NAME", default="")):
    raise ImproperlyConfigured(
        "오브젝트 스토리지 버킷이 없습니다(BUCKET_NAME 또는 AWS_STORAGE_BUCKET_NAME). "
        "운영에서 파일시스템 스토리지를 쓰면 재배포 때 스캔·사진이 사라집니다."
    )

# Fly 프록시 뒤 HTTPS 인식
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default=True)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# 프런트(Vercel)와 API(Fly)가 다른 호스트에 산다 — `lms.hjcedu.com` 과 `api.hjcedu.com`.
# 쿠키를 `.hjcedu.com` 으로 발급해야 두 호스트가 같은 세션을 본다.
# **비워 두면 안 된다**: 기본값이면 쿠키가 `api.hjcedu.com` 전용으로 발급돼
# 프런트에서 로그인 상태가 유지되지 않는다.
# 값이 없으면(로컬·단일 호스트) Django 기본 동작 그대로 — None 이 기본이다.
SESSION_COOKIE_DOMAIN = env("SESSION_COOKIE_DOMAIN", default=None)
CSRF_COOKIE_DOMAIN = env("CSRF_COOKIE_DOMAIN", default=None)
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

# 알림 채널 — 실업체(알리고, docs/decisions.md §3-1). 자격증명은 fly secrets 로
# 주입하고, 비어 있으면 발송이 "API 키가 설정되지 않았습니다" 로 실패한다
# (조용한 성공 없음). 앱푸시는 아직 어댑터가 없다 — 구현체가 생길 때 한 줄 추가한다.
_ALIGO = "apps.notifications.aligo.AligoAdapter"
NOTIFICATION_CHANNEL_BACKENDS = {
    "카카오알림톡": _ALIGO,
    "문자": _ALIGO,
}

# 결제 제공자 — 실업체(결제선생). 알림 채널과 같은 축이다: **구현체 선택은
# 설정 모듈이 정하고 `.env` 에는 자격증명만 둔다.** `.env` 에 두면 개발용
# 파일 하나가 dev 의 Fake 를 덮어써 로컬에서 진짜 청구서가 나간다(2026-08-11
# 실측 — 그렇게 되어 있었다).
#
# **연동 검수 통과 전까지는 운영 키가 없다.** 자격증명이 비면 청구가
# `PermanentPaymentError` 로 실패한다(조용한 성공 없음).
PAYMENT_PROVIDER_BACKEND = "apps.payments.payssam.PayssamAdapter"

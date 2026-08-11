"""개발 설정 — 로컬. runserver + docker-compose(PG·Redis) 전제."""
from .base import *  # noqa: F401,F403
from .base import env

DEBUG = True
# 리터럴 재대입은 ALLOWED_HOSTS 환경변수를 무력화하므로 env.list 패턴 유지.
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1", "0.0.0.0"])

# DRF 권한은 base 의 IsAuthenticated 를 그대로 쓴다. 과거의 AllowAny 전역
# 오버라이드는 진짜 인증 도입(2026-07-22)과 함께 제거 — dev 편의는 테스트
# 계정 로그인으로 해결한다(감사 지적 사항).

# 이메일은 콘솔로 출력(실발송 없음).
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# 알림도 기계 밖으로 나가지 않는다 — 보관만 하는 Fake 어댑터
# (apps/notifications/channels.py). 운영은 prod.py 가 솔라피를 물린다.
_FAKE_CHANNEL = "apps.notifications.channels.FakeChannelAdapter"
NOTIFICATION_CHANNEL_BACKENDS = {
    "카카오알림톡": _FAKE_CHANNEL,
    "문자": _FAKE_CHANNEL,
    "앱푸시": _FAKE_CHANNEL,
}

# 청구서도 기계 밖으로 나가지 않는다(apps/payments/provider.py).
# **시드 연락처는 진짜 번호일 수 있다** — `01010000006` 같은 값은 실제로 쓰는
# 사람이 있을 수 있고, 샌드박스 키라도 sendType=TALK 는 그 번호로 카카오톡을
# 보낸다. 로컬에서 구매 버튼을 눌러 보는 것만으로 모르는 사람에게 청구서가
# 가는 일을 막는다. 운영은 prod.py 가 결제선생을 물린다.
PAYMENT_PROVIDER_BACKEND = "apps.payments.provider.FakePaymentAdapter"

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
# 리터럴 재대입은 환경변수를 무력화한다(위 ALLOWED_HOSTS 와 같은 함정) —
# 잔액 조회처럼 **보내지 않는** 호출을 실제 업체로 확인해 보려면 한 번씩
# 갈아 끼울 수 있어야 하므로 env 기본값으로 둔다.
PAYMENT_PROVIDER_BACKEND = env(
    "PAYMENT_PROVIDER_BACKEND", default="apps.payments.provider.FakePaymentAdapter"
)

# ⚠ **테스트 전용.** 당일 클리닉 신청을 연다(운영은 전날 마감 — PRD 3.2.4).
# 감독 흐름(봇 입장 → 녹음 → 전사)을 신청·배정 경로 그대로 확인하려면 오늘
# 안에 끝나는 클리닉이 필요한데, 전날 마감 때문에 만들 방법이 없어서 뚫어 둔다.
# **운영 설정(prod.py)에는 절대 넣지 않는다.**
CLINIC_ALLOW_SAME_DAY = True

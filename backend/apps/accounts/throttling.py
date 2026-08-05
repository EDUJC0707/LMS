"""로그인 시도 제한 — 표적 공격 전제(2026-08-05).

우리 로그인 아이디는 **추측 가능하다**: `{이름}{번호4자리}`, 학부모는 `{자녀아이디}p`.
학생 이름만 알면 아이디의 대부분이 나온다. 그래서 막아야 할 것은 무작위 스캔이 아니라
**아는 사람을 노린 시도**다(사용자 2026-08-05: 경쟁 강사가 시도할 수 있다).

한도가 둘인 이유:

- **계정별**(`ACCOUNT_MAX_FAILURES`) — 진짜 방어선. 공격자가 IP 를 바꿔도 따라간다.
- **IP별**(`IP_MAX_FAILURES`) — 한 곳에서 계정을 갈아 가며 훑는 것을 잡는 보조선.
  학원 와이파이가 공용 IP 라 **넉넉해야 한다** — 빠듯하면 남의 실패로 학생이 잠긴다.

**영구 잠금은 두지 않는다.** 잠금은 무기가 된다 — 시험 전날 남의 아이디로 일부러
실패시키면 그게 곧 서비스 거부다. 시간이 지나면 저절로 풀린다.
"""
from datetime import timedelta

from django.utils import timezone

from .models import LoginAttempt

#: 한 계정을 몇 번 틀리면 막을지. 실수로 몇 번 틀리는 것은 통과해야 한다.
ACCOUNT_MAX_FAILURES = 5

#: 한 IP 가 계정을 갈아 가며 몇 번 틀리면 막을지. 학원 공용 IP 를 감안해 넉넉히.
IP_MAX_FAILURES = 30

#: 실패를 세는 창. 지나면 저절로 풀린다(영구 잠금 없음).
FAILURE_WINDOW = timedelta(minutes=5)

THROTTLED_MESSAGE = "로그인 시도가 너무 많습니다. 잠시 후 다시 시도해 주세요."


def client_ip(request) -> str | None:
    """요청의 실제 클라이언트 IP.

    **`REMOTE_ADDR` 을 그대로 쓰면 안 된다** — Fly 뒤에서는 그게 프록시라
    모든 사용자가 한 IP 로 묶이고, IP 한도가 전체를 한꺼번에 잠근다.

    `X-Forwarded-For` 는 클라이언트가 위조할 수 있다. 그래서 이 값에 기대는 것은
    **보조선인 IP 한도뿐**이고, 진짜 방어선인 계정별 한도는 이 값을 쓰지 않는다.
    위조로 얻을 수 있는 것은 IP 한도 회피뿐이며 계정 한도는 그대로 걸린다.
    """
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        # 프록시 체인은 왼쪽이 클라이언트다.
        return forwarded.split(",")[0].strip() or None
    return request.META.get("REMOTE_ADDR") or None


def is_throttled(login_id: str, ip: str | None) -> bool:
    """이 시도를 막아야 하나. **authenticate 앞에서** 부른다.

    뒤에서 부르면 한도를 소진한 공격자가 다음 시도에 비밀번호를 맞혔을 때
    그대로 들어온다 — 제한이 있으나 마나가 된다.
    """
    since = timezone.now() - FAILURE_WINDOW
    recent = LoginAttempt.objects.filter(created_at__gte=since)

    if recent.filter(login_id=login_id).count() >= ACCOUNT_MAX_FAILURES:
        return True
    if ip and recent.filter(ip=ip).count() >= IP_MAX_FAILURES:
        return True
    return False


def record_failure(login_id: str, ip: str | None) -> None:
    """실패 1건을 남긴다. 성공은 남기지 않는다(위 모델 docstring 참조)."""
    LoginAttempt.objects.create(login_id=login_id, ip=ip)

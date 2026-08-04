"""알림 발송 오케스트레이션 — 한 행을 실제로 내보내는 단 하나의 진입점.

Celery 를 모른다. 태스크는 이 함수를 부르고 재시도 정책만 얹는다 — 그래야 발송
규칙을 워커 없이 테스트할 수 있고, 나중에 관리자 화면의 수동 재발송이 붙어도
같은 규칙을 두 번 쓰지 않는다.

**대상 3분기 → 연락처는 여기서만 풀린다.** 학생은 `students` 에 phone 컬럼이
없어(설계 도메인 1) 연락처가 `users` 행에 있고, 학부모는 `parents.phone`,
직원은 `users.phone` 이다. 세 군데가 다르므로 호출측마다 풀게 두면 곧 갈린다.

**상태 전이 계약**:

| 결과 | status | sent_at | error_msg |
|---|---|---|---|
| 성공 | `성공` | 발송 시각 | 비운다 |
| 영구 실패(번호 오류·템플릿 미승인·채널 미설정) | `실패` | NULL | 사유 |
| 일시 실패(타임아웃·5xx) | **`대기` 유지** | NULL | 사유 |

일시 실패에서 `실패` 로 쓰지 않는 이유: 재시도가 도는 동안 관리자 발송내역에
"실패"가 떴다 사라지는 깜빡임이 생기고, 실패 재발송 배치가 아직 살아 있는 건을
집어 이중 발송한다. 실패로 확정하는 것은 **재시도가 소진된 뒤**(tasks 소관)다.

그래서 일시 실패는 error_msg 를 **커밋한 뒤에** 예외를 올린다 — atomic 블록
안에서 그대로 던지면 사유까지 롤백돼 "왜 밀렸는지"가 사라진다.

**이미 나간 건은 다시 보내지 않는다.** 행을 `select_for_update` 로 잠그고 상태를
다시 확인하므로, 재시도와 재발송 배치가 같은 행에 겹쳐도 발송은 한 번이다.
"""
from django.db import transaction
from django.utils import timezone

from .channels import (
    Message,
    PermanentChannelError,
    TemporaryChannelError,
    get_adapter,
)
from .models import Notification

#: 이미 끝난 상태 — 재발송 대상이 아니다.
_TERMINAL = {Notification.Status.SUCCESS, Notification.Status.CONFIRMED}

_ERROR_MSG_MAX = Notification._meta.get_field("error_msg").max_length


def build_message(notification):
    """알림 행 → 중립 발송 요청. 연락처를 못 찾으면 `PermanentChannelError`.

    연락처가 없는 것은 다시 걸어도 같다(계정 미발급 학생, 연락처 미입력) —
    재시도가 아니라 사유를 남기고 끝내는 쪽이 맞다.
    """
    return Message(
        channel=notification.channel,
        type=notification.type,
        recipient=_recipient(notification),
        title=notification.title or "",
        body=notification.body or "",
    )


def deliver(notif_id, now=None):
    """알림 한 건을 보내고 상태를 전이시킨다. 갱신된 행을 돌려준다.

    일시 실패는 `TemporaryChannelError` 를 그대로 올린다(호출측이 재시도).
    영구 실패는 예외를 삼키고 `실패` 로 기록한다 — 다시 걸 이유가 없으므로
    태스크까지 올려 재시도 판정을 시킬 것이 없다.
    """
    now = now or timezone.now()
    with transaction.atomic():
        notification = (
            # of=("self",) — 대상 3분기가 전부 nullable FK 라 select_related 가
            # LEFT JOIN 을 만들고, Postgres 는 outer join 의 nullable 쪽에
            # FOR UPDATE 를 걸지 못한다. 잠글 것은 알림 행 하나뿐이다.
            Notification.objects.select_for_update(of=("self",))
            .select_related("student__user", "parent", "user")
            .get(pk=notif_id)
        )
        if notification.status in _TERMINAL:
            return notification
        try:
            get_adapter(notification.channel).send(build_message(notification))
        except PermanentChannelError as exc:
            _stamp(notification, Notification.Status.FAILED, error=exc)
            return notification
        except TemporaryChannelError as exc:
            _stamp(notification, Notification.Status.PENDING, error=exc)
            temporary = exc
        else:
            _stamp(notification, Notification.Status.SUCCESS, sent_at=now)
            return notification
    # atomic 을 빠져나온 뒤에 던진다 — 안에서 던지면 위 error_msg 가 함께 롤백된다.
    raise temporary


def _recipient(notification):
    """대상 3분기 → 연락처. 셋 중 정확히 하나가 채워져 있다(모델 clean 계약)."""
    if notification.student_id:
        account = notification.student.user
        return _require_phone(
            account.phone if account else "",
            f"학생 연락처가 없습니다(student_id={notification.student_id})",
        )
    if notification.parent_id:
        return _require_phone(
            notification.parent.phone,
            f"학부모 연락처가 없습니다(parent_id={notification.parent_id})",
        )
    if notification.user_id:
        return _require_phone(
            notification.user.phone,
            f"직원 연락처가 없습니다(user_id={notification.user_id})",
        )
    raise PermanentChannelError("알림 대상이 지정되지 않았습니다.")


def _require_phone(phone, reason):
    phone = (phone or "").strip()
    if not phone:
        raise PermanentChannelError(reason)
    return phone


def _stamp(notification, status, sent_at=None, error=None):
    notification.status = status
    notification.sent_at = sent_at
    notification.error_msg = str(error)[:_ERROR_MSG_MAX] if error else None
    notification.save(update_fields=["status", "sent_at", "error_msg"])

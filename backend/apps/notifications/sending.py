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
import logging

from django.db import transaction
from django.utils import timezone

from .channels import (
    Message,
    PermanentChannelError,
    TemporaryChannelError,
    get_adapter,
)
from .models import Notification

logger = logging.getLogger(__name__)

#: 이미 끝난 상태 — 재발송 대상이 아니다.
_TERMINAL = {Notification.Status.SUCCESS, Notification.Status.CONFIRMED}

_ERROR_MSG_MAX = Notification._meta.get_field("error_msg").max_length


def queue(
    *,
    type,
    channel,
    student=None,
    parent=None,
    user=None,
    title=None,
    body=None,
    ref_type=None,
    ref_id=None,
):
    """알림 행을 남기고 발송을 예약한다 — **이벤트 지점이 부르는 단 하나의 문.**

    행 생성과 발송 예약을 갈라 두면 곧 어긋난다: 행만 만들고 태스크를 안 거는
    자리가 생기면 그 알림은 재발송 배치가 집어갈 때까지(최대 유예 30분 + 배치
    주기) 나가지 않는다. 배치는 **그물이지 통로가 아니다.**

    **커밋 뒤에 건다**(`transaction.on_commit`). 알림 행은 거의 항상 다른 업무
    (출결 스탬프, 상담 종결)와 같은 트랜잭션에서 만들어진다 —
    - 커밋 전에 걸면 워커가 아직 보이지 않는 행을 집어 `DoesNotExist` 로 죽고,
    - 롤백된 뒤에 나가면 **일어나지도 않은 일의 알림**이 학부모에게 간다.
    트랜잭션 밖에서 부르면 on_commit 은 즉시 실행되므로 호출측은 신경 쓸 것이 없다.

    `full_clean` 을 거치는 이유: `objects.create` 는 clean 을 부르지 않아서 대상
    3분기(셋 중 하나)나 채널 오타가 그대로 행이 된다. 그런 행은 발송 시점에야
    조용히 실패한다 — 만드는 자리에서 막는다.
    """
    notification = Notification(
        student=student,
        parent=parent,
        user=user,
        channel=channel,
        type=type,
        title=title,
        body=body,
        ref_type=ref_type,
        ref_id=ref_id,
        status=Notification.Status.PENDING,
    )
    notification.full_clean()
    notification.save()
    transaction.on_commit(lambda: _dispatch(notification.notif_id))
    return notification


def _dispatch(notif_id):
    """태스크를 건다 — **거는 데 실패해도 업무를 뒤엎지 않는다.**

    브로커가 없으면(운영에 Redis·워커가 아직 없다 — `infra/DEPLOY.md` 6장)
    `delay` 가 터지는데, 이 콜백은 **커밋 뒤**에 돌기 때문에 그 예외는 이미
    끝난 업무 위로 올라간다. 2026-08-12 에 결제 취소가 그렇게 터졌다: 돈은
    돌아갔는데 화면에는 500 이 떴다. 계정 발급은 더 나쁘다 — 초기 비밀번호는
    응답에만 실리므로 응답이 사라지면 **만들어진 계정에 아무도 못 들어간다.**

    삼켜도 조용한 실패가 아니다: 행은 `대기` 로 남아 재발송 배치가 집어 간다
    (`tasks.retry_failed_notifications`). 여기서는 사유만 남긴다.
    """
    # tasks 가 이 모듈의 deliver 를 쓰므로 위로 import 하면 순환이 된다.
    from .tasks import send_notification

    try:
        send_notification.delay(notif_id)
    except Exception:
        logger.exception("알림 %s 발송을 걸지 못했습니다 — 재발송 배치가 집습니다.", notif_id)


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

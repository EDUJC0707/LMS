"""알림 발송 Celery 태스크 — 저장소의 **첫 `@shared_task`**.

> **워커는 아직 안 떠 있다.** `infra/DEPLOY.md` 6장의 보류 해제 트리거가 "첫
> `@shared_task` 작성 시점"이고, 이 파일이 그 시점이다. Redis 생성·secret 주입·
> `fly scale count worker=1` 3단계는 **아직 실행하지 않았다**(워커는 auto_stop
> 대상이 아니라 월 ~$3.3 이 상시로 나간다). 실제 발송을 켜는 날 그 3단계를 함께
> 돌린다.

발송 규칙은 여기 없다 — `sending.deliver` 가 전부 안다. 이 파일이 더하는 것은
**재시도 정책과 배치 선정**뿐이다.

**재시도 = 일시 오류에만.** 어댑터가 `TemporaryChannelError` 로 번역한 것만
다시 건다. 번호 오류·템플릿 미승인·채널 미설정은 `PermanentChannelError` 라
`deliver` 가 이미 `실패` 로 닫고 올라오지 않는다.

**실패 확정은 재시도가 소진된 뒤다.** 그 전까지 행은 `대기`로 남는다
(sending 의 상태 전이표 참조).
"""
import logging

from celery import shared_task
from celery.exceptions import MaxRetriesExceededError, Retry
from django.conf import settings
from django.utils import timezone

from .channels import TemporaryChannelError
from .models import Notification
from .sending import deliver

logger = logging.getLogger(__name__)

#: 재시도 간격(초)의 밑값 — 2의 거듭제곱으로 벌어진다(1분·2분·4분…).
RETRY_BACKOFF_BASE_SECONDS = 60
#: 한 번에 벌릴 수 있는 최대 간격 — 지수가 하루를 넘겨 버리는 것을 막는다.
RETRY_BACKOFF_MAX_SECONDS = 60 * 30


@shared_task(bind=True, name="notifications.send_notification")
def send_notification(self, notif_id):
    """알림 한 건을 보낸다. 일시 오류면 백오프 재시도, 소진되면 `실패` 확정."""
    max_retries = getattr(settings, "NOTIFICATION_MAX_RETRIES", 5)
    try:
        notification = deliver(notif_id)
    except Notification.DoesNotExist:
        # 이력이 지워진 뒤 도착한 태스크 — 다시 걸어도 행은 돌아오지 않는다.
        logger.warning("알림 %s 행이 없어 발송을 건너뜁니다.", notif_id)
        return None
    except TemporaryChannelError as exc:
        try:
            self.retry(
                exc=exc,
                max_retries=max_retries,
                countdown=_backoff(self.request.retries),
            )
        except Retry:
            raise  # 재시도가 예약됐다 — 행은 `대기` 그대로 둔다
        except (MaxRetriesExceededError, TemporaryChannelError):
            # 소진. `exc` 를 넘기면 celery 는 MaxRetriesExceededError 가 아니라
            # **원 예외를 다시 던진다** — 둘 다 같은 소진 신호로 받는다.
            _mark_exhausted(notif_id, exc)
            return Notification.Status.FAILED
    return notification.status


@shared_task(name="notifications.retry_failed_notifications")
def retry_failed_notifications():
    """실패·정체 알림을 다시 밀어 넣는다. 재발송을 건 notif_id 목록을 돌려준다.

    **선정창 두 개**(설정값):
    - `NOTIFICATION_RETRY_GRACE_MINUTES` 보다 **새 행은 건드리지 않는다** —
      아직 재시도가 돌고 있을 수 있고, 여기서 집으면 이중 발송이 된다.
    - `NOTIFICATION_RETRY_MAX_AGE_HOURS` 보다 **오래된 행도 건드리지 않는다** —
      지난 알림은 지금 보내야 의미가 없다. 그리고 이 상한이 **영구 실패 행의
      무한 재발송을 막는 유일한 울타리**다: 시도 횟수 컬럼을 두지 않기로 했으므로
      (스키마 불변 계약) 몇 번 걸었는지를 셀 자리가 없다.

    `대기`도 함께 집는 이유: 태스크가 유실되면 행이 `대기`로 굳는데, 그 행을
    되살릴 경로가 이 배치뿐이다. 조회는 `idx_notif_status` 부분 인덱스
    (status IN (대기, 실패))가 그대로 받는다.
    """
    now = timezone.now()
    grace = timezone.timedelta(minutes=getattr(settings, "NOTIFICATION_RETRY_GRACE_MINUTES", 30))
    max_age = timezone.timedelta(hours=getattr(settings, "NOTIFICATION_RETRY_MAX_AGE_HOURS", 24))
    batch_size = getattr(settings, "NOTIFICATION_RETRY_BATCH_SIZE", 200)

    notif_ids = list(
        Notification.objects.filter(
            status__in=[Notification.Status.PENDING, Notification.Status.FAILED],
            created_at__lte=now - grace,
            created_at__gte=now - max_age,
        )
        .order_by("created_at")
        .values_list("notif_id", flat=True)[:batch_size]
    )
    for notif_id in notif_ids:
        send_notification.delay(notif_id)
    if notif_ids:
        logger.info("알림 재발송 %d건을 다시 넣었습니다.", len(notif_ids))
    return notif_ids


def _backoff(retries):
    return min(RETRY_BACKOFF_BASE_SECONDS * (2**retries), RETRY_BACKOFF_MAX_SECONDS)


def _mark_exhausted(notif_id, exc):
    """재시도 소진 — 여기서 비로소 `실패`다(그 전까지는 `대기`)."""
    updated = Notification.objects.filter(pk=notif_id).exclude(
        status__in=[Notification.Status.SUCCESS, Notification.Status.CONFIRMED]
    ).update(
        status=Notification.Status.FAILED,
        error_msg=str(exc)[: Notification._meta.get_field("error_msg").max_length],
    )
    if updated:
        logger.warning("알림 %s 재시도 소진 — 실패로 확정합니다: %s", notif_id, exc)

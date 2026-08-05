"""발송 태스크 테스트 — 재시도 정책과 재발송 배치 선정 (설계 §4.5, PRD 3.1.2).

브로커 없이 돈다: Celery 를 eager 로 돌려 `.delay()` 가 그 자리에서 실행되게 하고,
결과는 DB 행으로 확인한다(호출 횟수가 아니라 실제 상태 전이를 본다).
"""
from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import Student, User
from config.celery import app as celery_app

from .channels import (
    ChannelAdapter,
    FakeChannelAdapter,
    PermanentChannelError,
    TemporaryChannelError,
)
from .models import Notification
from .tasks import retry_failed_notifications, send_notification

FAKE = "apps.notifications.channels.FakeChannelAdapter"
COUNTING_TEMPORARY = "apps.notifications.test_tasks.CountingTemporaryAdapter"
COUNTING_PERMANENT = "apps.notifications.test_tasks.CountingPermanentAdapter"


class CountingTemporaryAdapter(ChannelAdapter):
    calls = 0

    def send(self, message):
        CountingTemporaryAdapter.calls += 1
        raise TemporaryChannelError("업체 응답 없음")


class CountingPermanentAdapter(ChannelAdapter):
    calls = 0

    def send(self, message):
        CountingPermanentAdapter.calls += 1
        raise PermanentChannelError("수신 거부된 번호")


def make_student(matching_key="김하늘0001"):
    user = User.objects.create_user(
        matching_key, role=User.Role.STUDENT, name="김하늘", phone="01011112222"
    )
    return Student.objects.create(matching_key=matching_key, user=user)


class CeleryEagerMixin:
    """브로커 없이 태스크를 그 자리에서 실행시킨다."""

    def setUp(self):
        super().setUp()
        self._eager = celery_app.conf.task_always_eager
        celery_app.conf.task_always_eager = True
        self.addCleanup(setattr, celery_app.conf, "task_always_eager", self._eager)
        FakeChannelAdapter.outbox.clear()
        CountingTemporaryAdapter.calls = 0
        CountingPermanentAdapter.calls = 0


def make_notification(**kwargs):
    kwargs.setdefault("channel", Notification.Channel.KAKAO)
    kwargs.setdefault("type", Notification.Type.GRADE)
    return Notification.objects.create(**kwargs)


def age(notification, **delta):
    """auto_now_add 로 박힌 created_at 을 과거로 민다(배치 선정창 검증용)."""
    Notification.objects.filter(pk=notification.pk).update(
        created_at=timezone.now() - timedelta(**delta)
    )


class SendNotificationTaskTests(CeleryEagerMixin, TestCase):
    @override_settings(NOTIFICATION_CHANNEL_BACKENDS={"카카오알림톡": FAKE})
    def test_task_sends_and_marks_success(self):
        notif = make_notification(student=make_student())

        send_notification.delay(notif.notif_id)

        notif.refresh_from_db()
        self.assertEqual(notif.status, Notification.Status.SUCCESS)
        self.assertEqual(len(FakeChannelAdapter.outbox), 1)

    @override_settings(
        NOTIFICATION_CHANNEL_BACKENDS={"카카오알림톡": COUNTING_TEMPORARY},
        NOTIFICATION_MAX_RETRIES=2,
    )
    def test_temporary_error_is_retried_until_exhausted_then_failed(self):
        # 최초 1회 + 재시도 2회 = 3회 걸어 보고, 그때 비로소 실패로 확정한다.
        notif = make_notification(student=make_student())

        send_notification.apply(args=[notif.notif_id])

        self.assertEqual(CountingTemporaryAdapter.calls, 3)
        notif.refresh_from_db()
        self.assertEqual(notif.status, Notification.Status.FAILED)
        self.assertIn("업체 응답 없음", notif.error_msg)

    @override_settings(NOTIFICATION_CHANNEL_BACKENDS={"카카오알림톡": COUNTING_PERMANENT})
    def test_permanent_error_is_not_retried(self):
        notif = make_notification(student=make_student())

        send_notification.apply(args=[notif.notif_id])

        self.assertEqual(CountingPermanentAdapter.calls, 1)
        notif.refresh_from_db()
        self.assertEqual(notif.status, Notification.Status.FAILED)

    @override_settings(NOTIFICATION_CHANNEL_BACKENDS={"카카오알림톡": FAKE})
    def test_missing_row_is_not_retried(self):
        # 이력이 지워진 뒤 도착한 태스크 — 다시 걸어도 행은 돌아오지 않는다.
        result = send_notification.apply(args=[999999])

        self.assertTrue(result.successful())
        self.assertEqual(FakeChannelAdapter.outbox, [])


class RetryBatchTests(CeleryEagerMixin, TestCase):
    """실패 재발송 배치 — idx_notif_status 부분 인덱스(대기/실패)를 그대로 쓴다."""

    @override_settings(
        NOTIFICATION_CHANNEL_BACKENDS={"카카오알림톡": FAKE},
        NOTIFICATION_RETRY_GRACE_MINUTES=30,
        NOTIFICATION_RETRY_MAX_AGE_HOURS=24,
    )
    def test_batch_resends_failed_row_inside_the_window(self):
        notif = make_notification(student=make_student(), status=Notification.Status.FAILED)
        age(notif, hours=2)

        sent = retry_failed_notifications()

        self.assertEqual(sent, [notif.notif_id])
        notif.refresh_from_db()
        self.assertEqual(notif.status, Notification.Status.SUCCESS)

    @override_settings(
        NOTIFICATION_CHANNEL_BACKENDS={"카카오알림톡": FAKE},
        NOTIFICATION_RETRY_GRACE_MINUTES=30,
        NOTIFICATION_RETRY_MAX_AGE_HOURS=24,
    )
    def test_batch_picks_up_stranded_pending_rows(self):
        # 태스크가 유실돼 대기로 굳은 행 — 배치가 유일한 구제 경로다.
        notif = make_notification(student=make_student())
        age(notif, hours=2)

        self.assertEqual(retry_failed_notifications(), [notif.notif_id])

    @override_settings(
        NOTIFICATION_CHANNEL_BACKENDS={"카카오알림톡": FAKE},
        NOTIFICATION_RETRY_GRACE_MINUTES=30,
    )
    def test_batch_skips_rows_still_inside_the_grace_window(self):
        # 방금 만들어진 행은 아직 재시도가 돌고 있다 — 여기서 집으면 이중 발송이다.
        notif = make_notification(student=make_student())
        age(notif, minutes=5)

        self.assertEqual(retry_failed_notifications(), [])
        notif.refresh_from_db()
        self.assertEqual(notif.status, Notification.Status.PENDING)

    @override_settings(
        NOTIFICATION_CHANNEL_BACKENDS={"카카오알림톡": FAKE},
        NOTIFICATION_RETRY_GRACE_MINUTES=30,
        NOTIFICATION_RETRY_MAX_AGE_HOURS=24,
    )
    def test_batch_skips_rows_older_than_max_age(self):
        # 지난 알림은 지금 보내도 의미가 없고, 이 시간창이 영구 실패 행의
        # 무한 재발송을 막는 유일한 울타리다(시도 횟수 컬럼이 없다).
        notif = make_notification(student=make_student(), status=Notification.Status.FAILED)
        age(notif, hours=48)

        self.assertEqual(retry_failed_notifications(), [])

    @override_settings(NOTIFICATION_CHANNEL_BACKENDS={"카카오알림톡": FAKE})
    def test_batch_ignores_finished_rows(self):
        for status in (Notification.Status.SUCCESS, Notification.Status.CONFIRMED):
            notif = make_notification(student=make_student(f"김하늘{status}"), status=status)
            age(notif, hours=2)

        self.assertEqual(retry_failed_notifications(), [])
        self.assertEqual(FakeChannelAdapter.outbox, [])

    @override_settings(
        NOTIFICATION_CHANNEL_BACKENDS={"카카오알림톡": FAKE},
        NOTIFICATION_RETRY_GRACE_MINUTES=30,
        NOTIFICATION_RETRY_MAX_AGE_HOURS=24,
        NOTIFICATION_RETRY_BATCH_SIZE=1,
    )
    def test_batch_size_caps_one_run(self):
        for index in range(3):
            notif = make_notification(
                student=make_student(f"김하늘000{index}"), status=Notification.Status.FAILED
            )
            age(notif, hours=2)

        self.assertEqual(len(retry_failed_notifications()), 1)

"""발송 진입점 테스트 — 이벤트 지점이 알림을 거는 단 하나의 문.

핵심은 **커밋 경계**다. 알림 행은 거의 항상 다른 업무(출결 스탬프, 상담 종결)와
같은 트랜잭션 안에서 만들어진다. 커밋 전에 태스크를 걸면 워커가 아직 없는 행을
집어 `DoesNotExist` 로 죽고, 롤백되면 일어나지도 않은 일의 알림이 나간다.
"""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.test import TestCase, override_settings

from apps.accounts.models import Parent, Student, User
from config.celery import app as celery_app

from .channels import FakeChannelAdapter
from .models import Notification
from .sending import queue

FAKE = "apps.notifications.channels.FakeChannelAdapter"


def make_student(matching_key="김하늘0001"):
    user = User.objects.create_user(
        matching_key, role=User.Role.STUDENT, name="김하늘", phone="01011112222"
    )
    return Student.objects.create(matching_key=matching_key, user=user)


@override_settings(NOTIFICATION_CHANNEL_BACKENDS={"카카오알림톡": FAKE, "문자": FAKE})
class QueueTests(TestCase):
    def setUp(self):
        self._eager = celery_app.conf.task_always_eager
        celery_app.conf.task_always_eager = True
        self.addCleanup(setattr, celery_app.conf, "task_always_eager", self._eager)
        FakeChannelAdapter.outbox.clear()
        self.student = make_student()

    def test_queue_records_the_row_as_pending(self):
        notif = queue(
            type=Notification.Type.GRADE,
            channel=Notification.Channel.KAKAO,
            student=self.student,
            title="성적 안내",
        )

        notif.refresh_from_db()
        self.assertEqual(notif.status, Notification.Status.PENDING)
        self.assertEqual(notif.type, "성적")
        self.assertEqual(notif.title, "성적 안내")

    def test_queue_carries_the_soft_link(self):
        notif = queue(
            type=Notification.Type.CLINIC_ATTENDANCE,
            channel=Notification.Channel.KAKAO,
            student=self.student,
            title="클리닉 출석 안내",
            ref_type="clinic",
            ref_id=42,
        )

        self.assertEqual(notif.ref_type, "clinic")
        self.assertEqual(notif.ref_id, 42)

    def test_send_is_dispatched_after_commit(self):
        with self.captureOnCommitCallbacks(execute=True):
            notif = queue(
                type=Notification.Type.GRADE,
                channel=Notification.Channel.KAKAO,
                student=self.student,
            )

        notif.refresh_from_db()
        self.assertEqual(notif.status, Notification.Status.SUCCESS)
        self.assertEqual(len(FakeChannelAdapter.outbox), 1)

    def test_nothing_is_dispatched_before_commit(self):
        # 커밋 전에 걸면 워커가 아직 없는 행을 집는다.
        with self.captureOnCommitCallbacks(execute=False):
            queue(
                type=Notification.Type.GRADE,
                channel=Notification.Channel.KAKAO,
                student=self.student,
            )

        self.assertEqual(FakeChannelAdapter.outbox, [])

    def test_rollback_sends_nothing(self):
        # 업무가 취소됐는데 알림만 나가면 학부모에게 거짓말이 간다.
        with self.captureOnCommitCallbacks(execute=True):
            try:
                with transaction.atomic():
                    queue(
                        type=Notification.Type.GRADE,
                        channel=Notification.Channel.KAKAO,
                        student=self.student,
                    )
                    raise RuntimeError("업무 실패")
            except RuntimeError:
                pass

        self.assertFalse(Notification.objects.exists())
        self.assertEqual(FakeChannelAdapter.outbox, [])

    def test_two_targets_are_rejected(self):
        # objects.create 는 clean 을 안 부른다 — 진입점이 3분기 계약을 강제한다.
        parent = Parent.objects.create(name="김학부", phone="01033334444")
        with self.assertRaises(ValidationError):
            queue(
                type=Notification.Type.GRADE,
                channel=Notification.Channel.KAKAO,
                student=self.student,
                parent=parent,
            )
        self.assertFalse(Notification.objects.exists())

    def test_no_target_is_rejected(self):
        with self.assertRaises(ValidationError):
            queue(type=Notification.Type.GRADE, channel=Notification.Channel.KAKAO)
        self.assertFalse(Notification.objects.exists())

    def test_unknown_channel_is_rejected(self):
        # 채널은 값집합이다 — 오타가 행으로 굳으면 발송이 조용히 실패한다.
        with self.assertRaises(ValidationError):
            queue(type=Notification.Type.GRADE, channel="카톡", student=self.student)

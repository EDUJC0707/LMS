"""발송 오케스트레이션 테스트 — 대상 해석과 상태 전이 (설계 도메인 8, PRD 3.1.2).

여기서 지키는 것은 둘이다.
1. **대상 3분기 → 연락처**가 한 곳에서만 풀린다(학생은 users 행이 연락처를 든다).
2. **상태 전이가 재시도와 어긋나지 않는다** — 일시 오류는 `대기`를 유지하고,
   실패로 확정하는 것은 재시도가 소진된 뒤(태스크 소관)뿐이다.
"""
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import Parent, Student, User

from .channels import (
    ChannelAdapter,
    FakeChannelAdapter,
    PermanentChannelError,
    TemporaryChannelError,
)
from .models import Notification
from .sending import build_message, deliver

FAKE = "apps.notifications.channels.FakeChannelAdapter"
TEMPORARY = "apps.notifications.test_sending.AlwaysTemporaryAdapter"
PERMANENT = "apps.notifications.test_sending.AlwaysPermanentAdapter"
ALL_FAKE = {"카카오알림톡": FAKE, "문자": FAKE, "앱푸시": FAKE}


class AlwaysTemporaryAdapter(ChannelAdapter):
    def send(self, message):
        raise TemporaryChannelError("업체 응답 없음")


class AlwaysPermanentAdapter(ChannelAdapter):
    def send(self, message):
        raise PermanentChannelError("수신 거부된 번호")


def make_student(phone="01011112222", matching_key="김하늘0001"):
    user = User.objects.create_user(matching_key, role=User.Role.STUDENT, name="김하늘", phone=phone)
    return Student.objects.create(matching_key=matching_key, user=user)


def make_notification(**kwargs):
    kwargs.setdefault("channel", Notification.Channel.KAKAO)
    kwargs.setdefault("type", Notification.Type.GRADE)
    kwargs.setdefault("title", "성적 안내")
    kwargs.setdefault("body", "3회차 성적이 등록되었습니다.")
    return Notification.objects.create(**kwargs)


class RecipientTests(TestCase):
    """연락처는 대상 분기마다 다른 곳에 있다 — 해석은 한 군데서 끝낸다."""

    def test_student_recipient_comes_from_user_row(self):
        # students 에는 phone 컬럼이 없다(설계 도메인 1) — 연락처는 users 행이 든다.
        notif = make_notification(student=make_student(phone="01011112222"))
        self.assertEqual(build_message(notif).recipient, "01011112222")

    def test_parent_recipient_comes_from_parent_row(self):
        parent = Parent.objects.create(name="김학부", phone="01033334444")
        notif = make_notification(parent=parent)
        self.assertEqual(build_message(notif).recipient, "01033334444")

    def test_staff_recipient_comes_from_user_row(self):
        staff = User.objects.create_user(
            "박조교0003", role=User.Role.ASSISTANT, name="박조교", phone="01055556666"
        )
        notif = make_notification(user=staff)
        self.assertEqual(build_message(notif).recipient, "01055556666")

    def test_message_carries_channel_type_and_content(self):
        notif = make_notification(student=make_student())
        msg = build_message(notif)
        self.assertEqual(msg.channel, Notification.Channel.KAKAO)
        self.assertEqual(msg.type, Notification.Type.GRADE)
        self.assertEqual(msg.title, "성적 안내")
        self.assertEqual(msg.body, "3회차 성적이 등록되었습니다.")

    def test_null_title_and_body_become_empty_strings(self):
        notif = make_notification(student=make_student(), title=None, body=None)
        msg = build_message(notif)
        self.assertEqual(msg.title, "")
        self.assertEqual(msg.body, "")

    def test_student_without_account_is_permanent_error(self):
        # 계정 발급 전(D-1 배치 전) 학생 — 다시 걸어도 번호가 생기지 않는다.
        notif = make_notification(student=Student.objects.create(matching_key="장예준0029"))
        with self.assertRaises(PermanentChannelError):
            build_message(notif)

    def test_blank_phone_is_permanent_error(self):
        notif = make_notification(student=make_student(phone=""))
        with self.assertRaises(PermanentChannelError):
            build_message(notif)

    def test_notification_without_target_is_permanent_error(self):
        # 모델 clean 이 막는 상태지만 발송 경로도 스스로 방어한다
        # (일괄 생성이 full_clean 을 거치지 않는 경로가 있을 수 있다).
        with self.assertRaises(PermanentChannelError):
            build_message(make_notification())


@override_settings(NOTIFICATION_CHANNEL_BACKENDS=ALL_FAKE)
class DeliverSuccessTests(TestCase):
    def setUp(self):
        FakeChannelAdapter.outbox.clear()

    def test_success_stamps_status_and_sent_at(self):
        notif = make_notification(student=make_student())
        now = timezone.now()

        deliver(notif.notif_id, now=now)

        notif.refresh_from_db()
        self.assertEqual(notif.status, Notification.Status.SUCCESS)
        self.assertEqual(notif.sent_at, now)
        self.assertIsNone(notif.error_msg)

    def test_success_hands_the_message_to_the_channel_adapter(self):
        notif = make_notification(student=make_student(phone="01011112222"))

        deliver(notif.notif_id)

        self.assertEqual(len(FakeChannelAdapter.outbox), 1)
        self.assertEqual(FakeChannelAdapter.outbox[0].recipient, "01011112222")

    def test_already_sent_row_is_not_sent_again(self):
        # 재시도와 재발송 배치가 겹쳐도 이중 발송이 나지 않는다.
        notif = make_notification(student=make_student(), status=Notification.Status.SUCCESS)

        deliver(notif.notif_id)

        self.assertEqual(FakeChannelAdapter.outbox, [])

    def test_confirmed_row_is_not_sent_again(self):
        notif = make_notification(student=make_student(), status=Notification.Status.CONFIRMED)

        deliver(notif.notif_id)

        self.assertEqual(FakeChannelAdapter.outbox, [])

    def test_retry_after_failure_clears_the_old_error(self):
        notif = make_notification(
            student=make_student(),
            status=Notification.Status.FAILED,
            error_msg="업체 응답 없음",
        )

        deliver(notif.notif_id)

        notif.refresh_from_db()
        self.assertEqual(notif.status, Notification.Status.SUCCESS)
        self.assertIsNone(notif.error_msg)


class DeliverFailureTests(TestCase):
    @override_settings(NOTIFICATION_CHANNEL_BACKENDS={"카카오알림톡": PERMANENT})
    def test_permanent_error_marks_failed_with_reason(self):
        notif = make_notification(student=make_student())

        deliver(notif.notif_id)

        notif.refresh_from_db()
        self.assertEqual(notif.status, Notification.Status.FAILED)
        self.assertIn("수신 거부된 번호", notif.error_msg)
        self.assertIsNone(notif.sent_at)

    @override_settings(NOTIFICATION_CHANNEL_BACKENDS={})
    def test_unconfigured_channel_fails_loudly_instead_of_silent_success(self):
        notif = make_notification(student=make_student())

        deliver(notif.notif_id)

        notif.refresh_from_db()
        self.assertEqual(notif.status, Notification.Status.FAILED)
        self.assertIn("설정", notif.error_msg)

    @override_settings(NOTIFICATION_CHANNEL_BACKENDS={"카카오알림톡": TEMPORARY})
    def test_temporary_error_keeps_status_pending_and_reraises(self):
        # 재시도가 도는 동안은 아직 실패가 아니다 — 실패 확정은 소진 뒤(태스크 소관).
        notif = make_notification(student=make_student())

        with self.assertRaises(TemporaryChannelError):
            deliver(notif.notif_id)

        notif.refresh_from_db()
        self.assertEqual(notif.status, Notification.Status.PENDING)
        self.assertIn("업체 응답 없음", notif.error_msg)
        self.assertIsNone(notif.sent_at)

    @override_settings(NOTIFICATION_CHANNEL_BACKENDS={"카카오알림톡": TEMPORARY})
    def test_temporary_error_does_not_lose_the_error_on_rollback(self):
        # 예외를 던지면서도 error_msg 는 남아야 한다 — 남지 않으면 왜 밀렸는지
        # 관리자가 알 길이 없다.
        notif = make_notification(student=make_student())
        with self.assertRaises(TemporaryChannelError):
            deliver(notif.notif_id)
        self.assertEqual(
            Notification.objects.get(pk=notif.pk).error_msg, "업체 응답 없음"
        )

    @override_settings(NOTIFICATION_CHANNEL_BACKENDS=ALL_FAKE)
    def test_missing_recipient_marks_failed_without_calling_adapter(self):
        FakeChannelAdapter.outbox.clear()
        notif = make_notification(student=Student.objects.create(matching_key="장예준0029"))

        deliver(notif.notif_id)

        notif.refresh_from_db()
        self.assertEqual(notif.status, Notification.Status.FAILED)
        self.assertEqual(FakeChannelAdapter.outbox, [])

    @override_settings(NOTIFICATION_CHANNEL_BACKENDS={"카카오알림톡": PERMANENT})
    def test_error_msg_is_truncated_to_column_width(self):
        # error_msg 는 300자다 — 업체가 긴 응답을 주면 저장이 터진다.
        notif = make_notification(student=make_student())
        with self.settings(NOTIFICATION_CHANNEL_BACKENDS={"카카오알림톡": PERMANENT}):
            deliver(notif.notif_id)
        notif.refresh_from_db()
        self.assertLessEqual(len(notif.error_msg), 300)


class VendorNeutralityTests(TestCase):
    def test_delivery_writes_only_neutral_columns(self):
        # 업체 종속 컬럼 금지(key_considerations §4) — 발송 경로가 기록하는 것은
        # status/sent_at/error_msg 뿐이고, 업체 참조 ID 를 담을 자리가 없다.
        field_names = {f.name for f in Notification._meta.get_fields()}
        self.assertFalse({"external_ref", "provider", "solapi_message_id"} & field_names)

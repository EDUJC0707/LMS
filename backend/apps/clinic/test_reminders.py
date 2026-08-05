"""클리닉 시작 전 리마인더 — 링크가 열리기 직전에 학생에게 알린다.

링크는 시작 5분 전부터 학생 화면에 뜬다(`booking.CLINIC_LINK_LEAD`). 그 시각에
학생이 화면을 보고 있을 이유가 없으므로 알림이 그 자리를 메운다.

여기서 고정하는 것:
  ① 창: 시작 6분 전부터 — cron 이 1분마다 돌아 최대 1분 늦어도 링크가 열리는
     5분 전까지는 도착한다
  ② **두 번 보내지 않는다** — 매분 도는 배치라 중복이 기본값이다
  ③ 이미 시작했거나 승인배정이 아닌 건은 건드리지 않는다
"""
import datetime

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import Student, User
from apps.grades.models import Exam
from apps.notifications.models import Notification

from . import reminders
from .models import ClinicRequest, ClinicSlot

WED = datetime.date(2026, 7, 22)
FAKE_CHANNEL = "apps.notifications.channels.FakeChannelAdapter"


@override_settings(
    NOTIFICATION_CHANNEL_BACKENDS={Notification.Channel.KAKAO: FAKE_CHANNEL},
    CELERY_TASK_ALWAYS_EAGER=True,
)
class ClinicReminderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.student = Student.objects.create(
            user=User.objects.create_user(
                login_id="rm-stu", password="pw-Secret-77!", name="김하늘",
                role=User.Role.STUDENT, phone="01033334444",
            ),
            matching_key="김하늘0001",
        )
        cls.exam = Exam.objects.create(name="7월 모의고사", exam_date=WED)
        cls.slot = ClinicSlot.objects.create(
            weekday=3, start_time=datetime.time(19, 0), end_time=datetime.time(20, 0)
        )

    def make_request(self, **extra):
        extra.setdefault("status", ClinicRequest.Status.APPROVED)
        extra.setdefault("conference_url", "https://meet.google.com/a-b-c")
        return ClinicRequest.objects.create(
            student=self.student,
            exam=self.exam,
            slot=self.slot,
            requested_date=datetime.date(2026, 8, 5),
            requested_time=datetime.time(19, 0),
            **extra,
        )

    def at(self, minutes_before):
        """클리닉 시작 `minutes_before` 분 전 시각."""
        start = timezone.make_aware(datetime.datetime(2026, 8, 5, 19, 0))
        return start - datetime.timedelta(minutes=minutes_before)

    def reminders_for(self, request):
        return Notification.objects.filter(
            type=Notification.Type.CLINIC_REMINDER, ref_id=request.clinic_id
        )

    # ① 창 -----------------------------------------------------------------

    def test_sends_six_minutes_before(self):
        request = self.make_request()
        reminders.send_due(now=self.at(6))
        self.assertEqual(self.reminders_for(request).count(), 1)

    def test_silent_well_before_the_window(self):
        request = self.make_request()
        reminders.send_due(now=self.at(30))
        self.assertEqual(self.reminders_for(request).count(), 0)

    def test_still_sends_if_a_minute_was_missed(self):
        # cron 이 한 번 걸러도 링크가 열리기 전에는 도착해야 한다
        request = self.make_request()
        reminders.send_due(now=self.at(5))
        self.assertEqual(self.reminders_for(request).count(), 1)

    def test_does_not_send_after_it_started(self):
        request = self.make_request()
        reminders.send_due(now=self.at(-1))
        self.assertEqual(self.reminders_for(request).count(), 0)

    # ② 중복 ---------------------------------------------------------------

    def test_running_every_minute_sends_once(self):
        request = self.make_request()
        for minute in (6, 5):
            reminders.send_due(now=self.at(minute))
        self.assertEqual(self.reminders_for(request).count(), 1)

    # ③ 대상 ---------------------------------------------------------------

    def test_skips_requests_that_were_not_assigned(self):
        request = self.make_request(status=ClinicRequest.Status.PENDING)
        reminders.send_due(now=self.at(6))
        self.assertEqual(self.reminders_for(request).count(), 0)

    def test_skips_cancelled_requests(self):
        request = self.make_request(status=ClinicRequest.Status.CANCELLED)
        reminders.send_due(now=self.at(6))
        self.assertEqual(self.reminders_for(request).count(), 0)

    # 내용 -----------------------------------------------------------------

    def test_message_carries_the_start_time(self):
        # 학생이 "몇 시 것" 인지 알아야 한다 — 하루에 여러 건일 수 있다
        request = self.make_request()
        reminders.send_due(now=self.at(6))
        body = self.reminders_for(request).get().body
        self.assertIn("19:00", body)

    def test_goes_to_the_student(self):
        request = self.make_request()
        reminders.send_due(now=self.at(6))
        notification = self.reminders_for(request).get()
        self.assertEqual(notification.student_id, self.student.pk)
        self.assertIsNone(notification.parent_id)
        self.assertEqual(notification.ref_type, "clinic")

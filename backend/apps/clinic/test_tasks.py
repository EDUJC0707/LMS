"""수집 태스크 — beat 가 주기적으로 부르는 자리.

태스크 본문은 얇다(서비스 한 줄 호출). 그래서 여기서 잡는 것은 로직이 아니라
**배선**이다: 이름이 안 바뀌었는가, beat 일정에 실제로 등록돼 있는가, 예외가
새어 나가 워커를 죽이지 않는가.
"""
import datetime
from unittest import mock

from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import Student, User
from apps.notifications.models import Notification

from .conferencing import PermanentConferenceError
from .models import ClinicRequest
from .tasks import (
    COLLECT_TASK_NAME,
    REMINDER_TASK_NAME,
    collect_clinic_supervision,
    send_clinic_reminders,
)

REMINDER = Notification.Type.CLINIC_REMINDER
ABSENT = Notification.Type.CLINIC_NOSHOW_CHECK


class CollectTaskTests(SimpleTestCase):
    def test_delegates_to_the_service(self):
        counts = {"collected": 2, "waiting": 0, "failed": 0}
        with mock.patch("apps.clinic.tasks.supervision.collect") as collect:
            collect.return_value = counts
            self.assertEqual(collect_clinic_supervision(), counts)
        collect.assert_called_once_with()

    def test_a_broken_provider_does_not_kill_the_worker(self):
        # 어댑터 자체를 못 만드는 경우(설정 누락·자격증명 만료)는 다음 주기에
        # 다시 걸린다. 예외를 그대로 올리면 워커 로그가 그걸로 덮인다.
        with mock.patch("apps.clinic.tasks.supervision.collect") as collect:
            collect.side_effect = PermanentConferenceError("자격증명이 없습니다")
            result = collect_clinic_supervision()
        self.assertIn("자격증명", result["error"])


class BeatScheduleTests(SimpleTestCase):
    def test_task_is_on_the_beat_schedule(self):
        # 태스크만 쓰고 일정에 안 걸면 아무도 안 부른다 — 조용히 안 도는 종류다
        from django.conf import settings

        entries = settings.CELERY_BEAT_SCHEDULE.values()
        self.assertIn(COLLECT_TASK_NAME, [entry["task"] for entry in entries])

    @override_settings()
    def test_runs_at_least_twice_an_hour(self):
        # 회의가 끝나고 자료가 생기기까지 몇 분, 수집은 30분을 기다린다.
        # 주기가 그보다 성기면 대기 시간이 주기만큼 통째로 늘어난다.
        from django.conf import settings

        entry = next(
            e for e in settings.CELERY_BEAT_SCHEDULE.values() if e["task"] == COLLECT_TASK_NAME
        )
        self.assertLessEqual(entry["schedule"], 30 * 60)

    def test_beat_still_carries_the_other_tracks_entry(self):
        # 같은 딕셔너리를 여러 트랙이 쓴다 — 새 대입으로 덮으면 조용히 사라진다
        from django.conf import settings

        self.assertIn("retry-failed-notifications", settings.CELERY_BEAT_SCHEDULE)


class ClinicReminderTaskTests(TestCase):
    """5분 전 · 5분 후 미참석 — FLOW 3-7 의 그 두 시점."""

    #: 자정을 넘나들며 날짜가 갈리지 않도록 시각을 고정한다 —
    #: 태스크가 `now` 를 받는 이유가 그것이다(`sending.deliver` 선례).
    NOW = timezone.make_aware(datetime.datetime(2026, 7, 22, 19, 0))

    @classmethod
    def setUpTestData(cls):
        cls.student = Student.objects.create(
            user=User.objects.create_user(
                login_id="rm-stu", password="pw-Secret-77!", name="학생", role=User.Role.STUDENT
            ),
            matching_key="3_7777",
        )

    def approved(self, start, attendance=None):
        return ClinicRequest.objects.create(
            student=self.student,
            requested_date=start.date(),
            requested_time=start.time(),
            status=ClinicRequest.Status.APPROVED,
            attendance_status=attendance,
        )

    def rows(self, type_):
        return Notification.objects.filter(type=type_)

    def test_five_minutes_before_only(self):
        now = self.NOW
        soon = self.approved(now + datetime.timedelta(minutes=4))
        self.approved(now + datetime.timedelta(hours=3))  # 아직 멀었다
        counts = send_clinic_reminders(self.NOW)
        self.assertEqual(counts["reminder"], 1)
        self.assertEqual([row.ref_id for row in self.rows(REMINDER)], [soon.clinic_id])

    def test_reminder_is_queued_once_even_if_beat_runs_again(self):
        self.approved(self.NOW + datetime.timedelta(minutes=4))
        send_clinic_reminders(self.NOW)
        self.assertEqual(send_clinic_reminders(self.NOW)["reminder"], 0)
        self.assertEqual(self.rows(REMINDER).count(), 1)

    def test_absent_text_only_while_attendance_is_unmarked(self):
        now = self.NOW
        waiting = self.approved(now - datetime.timedelta(minutes=6))
        self.approved(
            now - datetime.timedelta(minutes=6), ClinicRequest.AttendanceStatus.PRESENT
        )
        counts = send_clinic_reminders(self.NOW)
        self.assertEqual(counts["absent"], 1)
        self.assertEqual([row.ref_id for row in self.rows(ABSENT)], [waiting.clinic_id])

    def test_absent_text_does_not_chase_hours_later(self):
        self.approved(self.NOW - datetime.timedelta(hours=2))
        self.assertEqual(send_clinic_reminders(self.NOW)["absent"], 0)

    def test_only_approved_requests_get_called(self):
        soon = self.NOW + datetime.timedelta(minutes=4)
        ClinicRequest.objects.create(
            student=self.student,
            requested_date=soon.date(),
            requested_time=soon.time(),
            status=ClinicRequest.Status.CANCELLED,
        )
        self.assertEqual(send_clinic_reminders(self.NOW)["reminder"], 0)

    def test_task_is_on_the_beat_schedule_every_minute(self):
        # "5분 전"이 5분 전이려면 주기가 그보다 촘촘해야 한다.
        from django.conf import settings

        entry = next(
            e for e in settings.CELERY_BEAT_SCHEDULE.values() if e["task"] == REMINDER_TASK_NAME
        )
        self.assertLessEqual(entry["schedule"], 60)

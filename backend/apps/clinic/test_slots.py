"""커리의 클리닉 창 → 슬롯 표 (FLOW 1-1·3-7).

2026-08-19 대표 구술로 두 전제가 뒤집혔다 — ① 시간대는 커리가 갖는다
② 정원은 클리닉 조교 수다. 여기서 지키는 것은 그 둘이 낳는 결과다.

**고친 날 이후부터만 적용된다**가 이 파일의 축이다. 창을 좁히거나 정원을
줄여도 이미 잡힌 신청은 안 움직인다 — 소급해 옮기면 학생이 온다고 한 시간이
말없이 바뀐다.
"""
import datetime

from django.test import TestCase

from apps.curriculum.models import Course

from . import slots
from .models import ClinicSlot


class HourlyWindowsTests(TestCase):
    def test_splits_the_window_into_hours(self):
        got = slots.hourly_windows(datetime.time(15, 0), datetime.time(18, 0))

        self.assertEqual(
            got,
            [
                (datetime.time(15, 0), datetime.time(16, 0)),
                (datetime.time(16, 0), datetime.time(17, 0)),
                (datetime.time(17, 0), datetime.time(18, 0)),
            ],
        )

    def test_drops_the_leftover_under_an_hour(self):
        """반 시간짜리 클리닉은 없다 — 21:00~21:30 은 슬롯이 되지 않는다."""
        got = slots.hourly_windows(datetime.time(20, 0), datetime.time(21, 30))

        self.assertEqual(got, [(datetime.time(20, 0), datetime.time(21, 0))])

    def test_empty_window_makes_no_slots(self):
        self.assertEqual(slots.hourly_windows(None, None), [])
        self.assertEqual(
            slots.hourly_windows(datetime.time(19, 0), datetime.time(19, 0)), []
        )


class SyncCourseSlotsTests(TestCase):
    def setUp(self):
        self.course = Course.objects.create(name="로직엔제", total_weeks=8)

    def _set(self, start, end):
        self.course.clinic_start_time = start
        self.course.clinic_end_time = end
        self.course.save(update_fields=["clinic_start_time", "clinic_end_time"])
        return slots.sync_course_slots(self.course)

    def test_stands_up_weekday_slots_from_the_window(self):
        created, revived, retired = self._set(datetime.time(15, 0), datetime.time(18, 0))

        self.assertEqual((created, revived, retired), (15, 0, 0))  # 월~금 × 3시간
        active = ClinicSlot.objects.filter(course=self.course, is_active=True)
        self.assertEqual(sorted(set(active.values_list("weekday", flat=True))), [1, 2, 3, 4, 5])

    def test_never_opens_the_weekend(self):
        self._set(datetime.time(15, 0), datetime.time(16, 0))

        weekdays = set(ClinicSlot.objects.values_list("weekday", flat=True))
        self.assertNotIn(0, weekdays)  # 일
        self.assertNotIn(6, weekdays)  # 토

    def test_narrowing_the_window_retires_instead_of_deleting(self):
        """빠진 시간은 지우지 않는다 — 그 시간에 잡아 둔 신청이 참조하고 있다."""
        self._set(datetime.time(15, 0), datetime.time(18, 0))

        self._set(datetime.time(15, 0), datetime.time(16, 0))

        self.assertEqual(ClinicSlot.objects.count(), 15)  # 행은 그대로
        self.assertEqual(ClinicSlot.objects.filter(is_active=True).count(), 5)
        self.assertFalse(
            ClinicSlot.objects.filter(start_time=datetime.time(17, 0), is_active=True).exists()
        )

    def test_widening_revives_the_same_rows(self):
        """되살릴 때 새 행을 만들지 않는다 — 만들면 옛 신청이 죽은 행에 남는다."""
        self._set(datetime.time(15, 0), datetime.time(18, 0))
        self._set(datetime.time(15, 0), datetime.time(16, 0))

        created, revived, retired = self._set(datetime.time(15, 0), datetime.time(18, 0))

        self.assertEqual((created, revived, retired), (0, 10, 0))
        self.assertEqual(ClinicSlot.objects.count(), 15)

    def test_clearing_the_window_closes_the_clinic(self):
        self._set(datetime.time(15, 0), datetime.time(18, 0))

        self._set(None, None)

        self.assertEqual(ClinicSlot.objects.filter(is_active=True).count(), 0)

    def test_two_courses_can_hold_the_same_hour(self):
        """같은 19시라도 커리가 다르면 다른 슬롯이다 — 시간대는 커리가 갖는다."""
        other = Course.objects.create(name="오메가", total_weeks=8)
        other.clinic_start_time, other.clinic_end_time = (
            datetime.time(19, 0),
            datetime.time(20, 0),
        )
        other.save(update_fields=["clinic_start_time", "clinic_end_time"])

        self._set(datetime.time(19, 0), datetime.time(20, 0))
        slots.sync_course_slots(other)

        self.assertEqual(ClinicSlot.objects.filter(start_time=datetime.time(19, 0)).count(), 10)

    def test_new_slots_inherit_the_capacity_in_use(self):
        """정원은 전역이라 나중에 선 슬롯만 1 로 남으면 안 된다."""
        self._set(datetime.time(19, 0), datetime.time(20, 0))
        ClinicSlot.objects.update(capacity=2)

        self._set(datetime.time(19, 0), datetime.time(21, 0))

        self.assertEqual(set(ClinicSlot.objects.values_list("capacity", flat=True)), {2})


class SetCourseHoursTests(TestCase):
    def setUp(self):
        self.course = Course.objects.create(name="로직엔제", total_weeks=8)

    def test_stores_the_window_and_syncs(self):
        payload = slots.set_course_hours(self.course, "15:00", "18:00")

        self.assertEqual(payload["clinic_start_time"], "15:00")
        self.assertEqual(payload["slots"], {"created": 15, "revived": 0, "retired": 0})

    def test_rejects_half_a_window(self):
        with self.assertRaises(ValueError):
            slots.set_course_hours(self.course, "15:00", None)

    def test_rejects_a_backwards_window(self):
        with self.assertRaises(ValueError):
            slots.set_course_hours(self.course, "18:00", "15:00")

    def test_rejects_a_window_shorter_than_an_hour(self):
        with self.assertRaises(ValueError):
            slots.set_course_hours(self.course, "15:00", "15:30")

    def test_rejects_a_malformed_time(self):
        with self.assertRaises(ValueError):
            slots.set_course_hours(self.course, "3pm", "6pm")

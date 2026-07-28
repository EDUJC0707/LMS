"""날짜별 가용 시간 API 테스트 — GET /api/student/clinic/availability.

Calendly 형 흐름(날짜 선택 → 그 날 가능한 시간 목록 → 하나 선택)을 그릴 수
있는 **날짜 축 응답**을 검증한다. 기존 "요일 슬롯 + slot.next_date" 축은
달력을 만들 수 없어 폐기했고(booking._slot_list 제거), 슬롯 목록은 전부
이 API 로 옮겼다.

검증 축:
- 날짜 축: 요청 구간의 날짜마다 그 요일의 활성 슬롯 시간 목록
- 노출 판단: 비활성 슬롯·지난 날짜·8시 지난 당일은 **응답에서 제외**,
  마감은 사유와 함께 **표시**(PRD 3.2.4 "마감 표시" 요구)
- 정원 1: 활성 신청 1건이면 그 날짜·시간은 마감
- 구간 상한: 기본 14일 / 최대 31일, 역구간·형식 오류 400
- 자격(§4): 비대상·무판정·영구제한은 403 — 시간표 자체를 못 본다
- 쿼리 수: 날짜×슬롯이 늘어도 고정(N+1 회귀 방지)

시간 의미론: apps.clinic.booking.timezone.now 를 patch 해 고정(Asia/Seoul).
기준일 2026-07-22 은 수요일(모델 요일 축 0=일…6=토 → 수=3, 목=4, 금=5).
"""
import datetime
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import Student, User
from apps.grades.models import Exam

from .models import ClinicEligibility, ClinicRequest, ClinicSlot

PASSWORD = "pw-Secret-77!"
URL = "/api/student/clinic/availability"

TODAY = datetime.date(2026, 7, 22)  # 수
THU = datetime.date(2026, 7, 23)
NEXT_WED = datetime.date(2026, 7, 29)

NOW = timezone.make_aware(datetime.datetime(2026, 7, 22, 7, 0))
NOW_0759 = timezone.make_aware(datetime.datetime(2026, 7, 22, 7, 59))
NOW_0800 = timezone.make_aware(datetime.datetime(2026, 7, 22, 8, 0))


def freeze_now(at=NOW):
    return mock.patch("apps.clinic.booking.timezone.now", return_value=at)


def make_student(login_id, name):
    user = User.objects.create_user(
        login_id=login_id, password=PASSWORD, name=name, role=User.Role.STUDENT
    )
    return Student.objects.create(
        user=user,
        unique_id=f"uid-{login_id}",
        enrollment_status=Student.EnrollmentStatus.REGISTERED,
    )


class AvailabilityFixtureMixin:
    """수 2타임 + 목 1타임 + 금 1타임(비활성) · 대상/비대상/무판정/제한 학생."""

    @classmethod
    def setUpTestData(cls):
        cls.exam = Exam.objects.create(name="7월 모의고사", exam_date=datetime.date(2026, 7, 15))
        cls.wed_19 = ClinicSlot.objects.create(
            weekday=3, start_time=datetime.time(19, 0), end_time=datetime.time(20, 0)
        )
        cls.wed_20 = ClinicSlot.objects.create(
            weekday=3, start_time=datetime.time(20, 0), end_time=datetime.time(21, 0)
        )
        cls.thu_19 = ClinicSlot.objects.create(
            weekday=4, start_time=datetime.time(19, 0), end_time=datetime.time(20, 0)
        )
        cls.fri_off = ClinicSlot.objects.create(
            weekday=5,
            start_time=datetime.time(19, 0),
            end_time=datetime.time(20, 0),
            is_active=False,
        )
        cls.s_target = make_student("av-1", "박선호")
        cls.s_other = make_student("av-2", "한지원")
        cls.s_not = make_student("av-3", "오평균")
        cls.s_none = make_student("av-4", "무기록")
        cls.s_banned = make_student("av-5", "금지훈")
        cls.s_banned.clinic_banned = True
        cls.s_banned.save(update_fields=["clinic_banned"])
        cls.parent_user = User.objects.create_user(
            login_id="av-par", password=PASSWORD, name="학부모", role=User.Role.PARENT
        )
        for student in (cls.s_target, cls.s_other, cls.s_banned):
            ClinicEligibility.objects.create(exam=cls.exam, student=student, is_target=True)
        ClinicEligibility.objects.create(
            exam=cls.exam,
            student=cls.s_not,
            is_target=False,
            reason=ClinicEligibility.Reason.ABOVE_AVG,
        )

    def fetch(self, at=NOW, **params):
        with freeze_now(at):
            return self.client.get(URL, {"exam_id": self.exam.exam_id, **params})

    def days_by_date(self, at=NOW, **params):
        res = self.fetch(at=at, **params)
        self.assertEqual(res.status_code, 200, res.content)
        return {d["date"]: d for d in res.json()["days"]}

    def make_request_row(self, student, slot, requested_date, status=None):
        return ClinicRequest.objects.create(
            student=student,
            exam=self.exam,
            slot=slot,
            requested_date=requested_date,
            requested_time=slot.start_time,
            status=status or ClinicRequest.Status.PENDING,
        )


class ClinicAvailabilityTests(AvailabilityFixtureMixin, TestCase):
    def setUp(self):
        self.client.force_login(self.s_target.user)

    # --- 날짜 축 ----------------------------------------------------------

    def test_default_range_is_two_weeks_from_today(self):
        body = self.fetch().json()
        self.assertEqual(body["exam_id"], self.exam.exam_id)
        self.assertEqual(body["range"], {"from": "2026-07-22", "to": "2026-08-04"})
        dates = [d["date"] for d in body["days"]]
        # 14일 구간(7/22~8/4)에 든 수·목만 — 금은 비활성, 나머지 요일은 슬롯 없음
        self.assertEqual(
            dates, ["2026-07-22", "2026-07-23", "2026-07-29", "2026-07-30"]
        )
        self.assertEqual(body["days"][0]["weekday"], 3)

    def test_day_lists_active_times_of_that_weekday(self):
        day = self.days_by_date()["2026-07-22"]
        self.assertEqual(
            day["times"],
            [
                {
                    "slot_id": self.wed_19.slot_id,
                    "start_time": "19:00",
                    "end_time": "20:00",
                    "available": True,
                    "reason": None,
                },
                {
                    "slot_id": self.wed_20.slot_id,
                    "start_time": "20:00",
                    "end_time": "21:00",
                    "available": True,
                    "reason": None,
                },
            ],
        )
        self.assertEqual(len(self.days_by_date()["2026-07-23"]["times"]), 1)

    def test_inactive_slot_never_appears(self):
        # 8/3(월)까지 기본 구간에 금요일 7/24·7/31 이 들어 있지만 비활성이라 미노출
        dates = set(self.days_by_date())
        self.assertNotIn("2026-07-24", dates)
        self.assertNotIn("2026-07-31", dates)

    def test_days_without_active_slot_are_omitted(self):
        dates = set(self.days_by_date())
        self.assertNotIn("2026-07-25", dates)  # 토
        self.assertNotIn("2026-07-26", dates)  # 일

    def test_past_dates_are_clamped_to_today(self):
        body = self.fetch(**{"from": "2026-07-01", "to": "2026-07-23"}).json()
        self.assertEqual(body["range"], {"from": "2026-07-22", "to": "2026-07-23"})
        self.assertEqual([d["date"] for d in body["days"]], ["2026-07-22", "2026-07-23"])

    def test_today_dropped_after_same_day_cutoff(self):
        before = self.days_by_date(at=NOW_0759)
        self.assertIn("2026-07-22", before)
        after = self.days_by_date(at=NOW_0800)
        self.assertNotIn("2026-07-22", after)
        self.assertIn("2026-07-23", after)

    def test_fully_past_range_returns_no_days(self):
        body = self.fetch(**{"from": "2026-07-01", "to": "2026-07-10"}).json()
        self.assertEqual(body["days"], [])

    # --- 마감(정원 1) -----------------------------------------------------

    def test_single_active_request_closes_the_time(self):
        self.make_request_row(self.s_other, self.wed_19, NEXT_WED)
        times = {t["slot_id"]: t for t in self.days_by_date()["2026-07-29"]["times"]}
        closed = times[self.wed_19.slot_id]
        self.assertFalse(closed["available"])
        self.assertEqual(closed["reason"], "마감")
        # 같은 날 다른 시간은 그대로 열려 있다
        self.assertTrue(times[self.wed_20.slot_id]["available"])
        # 다른 날짜의 같은 슬롯도 영향 없다
        self.assertTrue(
            {t["slot_id"]: t for t in self.days_by_date()["2026-07-22"]["times"]}[
                self.wed_19.slot_id
            ]["available"]
        )

    def test_approved_request_also_closes(self):
        self.make_request_row(
            self.s_other, self.thu_19, THU, status=ClinicRequest.Status.APPROVED
        )
        times = {t["slot_id"]: t for t in self.days_by_date()["2026-07-23"]["times"]}
        self.assertFalse(times[self.thu_19.slot_id]["available"])

    def test_cancelled_and_rejected_do_not_close(self):
        self.make_request_row(
            self.s_other, self.thu_19, THU, status=ClinicRequest.Status.CANCELLED
        )
        self.make_request_row(
            self.s_none, self.thu_19, THU, status=ClinicRequest.Status.REJECTED
        )
        times = {t["slot_id"]: t for t in self.days_by_date()["2026-07-23"]["times"]}
        self.assertTrue(times[self.thu_19.slot_id]["available"])

    def test_own_request_is_marked_as_mine(self):
        self.make_request_row(self.s_target, self.wed_19, NEXT_WED)
        times = {t["slot_id"]: t for t in self.days_by_date()["2026-07-29"]["times"]}
        mine = times[self.wed_19.slot_id]
        self.assertFalse(mine["available"])
        self.assertEqual(mine["reason"], "내신청")

    # --- 구간 상한 --------------------------------------------------------

    def test_explicit_range(self):
        body = self.fetch(**{"from": "2026-07-29", "to": "2026-07-30"}).json()
        self.assertEqual(body["range"], {"from": "2026-07-29", "to": "2026-07-30"})
        self.assertEqual([d["date"] for d in body["days"]], ["2026-07-29", "2026-07-30"])

    def test_from_only_uses_default_span(self):
        body = self.fetch(**{"from": "2026-08-01"}).json()
        self.assertEqual(body["range"], {"from": "2026-08-01", "to": "2026-08-14"})

    def test_max_range_boundary(self):
        # 31일(포함)까지 허용, 32일은 400
        self.assertEqual(
            self.fetch(**{"from": "2026-07-22", "to": "2026-08-21"}).status_code, 200
        )
        self.assertEqual(
            self.fetch(**{"from": "2026-07-22", "to": "2026-08-22"}).status_code, 400
        )

    def test_reversed_range_400(self):
        self.assertEqual(
            self.fetch(**{"from": "2026-08-01", "to": "2026-07-30"}).status_code, 400
        )

    def test_bad_date_format_400(self):
        self.assertEqual(self.fetch(**{"from": "07/29/2026"}).status_code, 400)
        self.assertEqual(self.fetch(**{"to": "not-a-date"}).status_code, 400)

    def test_exam_id_required_and_validated(self):
        with freeze_now():
            self.assertEqual(self.client.get(URL).status_code, 400)
            self.assertEqual(self.client.get(URL, {"exam_id": "abc"}).status_code, 400)
            self.assertEqual(self.client.get(URL, {"exam_id": 999999}).status_code, 404)

    # --- 자격 게이트(§4) --------------------------------------------------

    def test_non_target_403(self):
        for student in (self.s_not, self.s_none):
            self.client.force_login(student.user)
            self.assertEqual(self.fetch().status_code, 403, student.unique_id)

    def test_banned_403(self):
        self.client.force_login(self.s_banned.user)
        self.assertEqual(self.fetch().status_code, 403)

    def test_role_gates(self):
        self.client.logout()
        self.assertEqual(self.fetch().status_code, 403)
        self.client.force_login(self.parent_user)
        self.assertEqual(self.fetch().status_code, 403)

    # --- 쿼리 수 ----------------------------------------------------------

    def test_query_count_is_flat_over_dates_and_slots(self):
        self.make_request_row(self.s_other, self.wed_19, NEXT_WED)
        self.make_request_row(self.s_none, self.thu_19, THU)
        # 세션 2 + 학생 1 + 시험 1 + 자격 1 + 슬롯 1 + 예약현황 집계 1
        with freeze_now(), self.assertNumQueries(7):
            self.client.get(URL, {"exam_id": self.exam.exam_id})
        # 구간을 최대(31일)로 늘려도 쿼리 수는 그대로 — 날짜×슬롯 루프에 쿼리 없음
        with freeze_now(), self.assertNumQueries(7):
            self.client.get(
                URL,
                {"exam_id": self.exam.exam_id, "from": "2026-07-22", "to": "2026-08-21"},
            )

"""날짜별 가용 시간 API 테스트 — GET /api/student/clinic/availability.

Calendly 형 흐름(날짜 선택 → 그 날 가능한 시간 목록 → 하나 선택)을 그릴 수
있는 **날짜 축 응답**을 검증한다. 기존 "요일 슬롯 + slot.next_date" 축은
달력을 만들 수 없어 폐기했고(booking._slot_list 제거), 슬롯 목록은 전부
이 API 로 옮겼다.

검증 축:
- 날짜 축: 요청 구간의 날짜마다 그 요일의 활성 슬롯 시간 목록
- 노출 판단: 비활성 슬롯·지난 날짜·오늘은 **응답에서 제외**(오늘은 시각과
  무관하게 항상 빠진다 — 당일 신청 불가), 마감은 사유와 함께 **표시**
  (PRD 3.2.4 "마감 표시" 요구)
- **신청 창구**(2026-07-29 확정): 구간은 내일에서 시작해 **시험 주 다음
  월요일**에서 끝난다. 더 먼 날짜를 요청해도 창구 끝으로 잘리고, 창구가
  지났으면 403 이 아니라 **빈 days**(자격은 있는데 기간이 끝난 것이라
  다른 사실이다)
- 정원 1: 활성 신청 1건이면 그 날짜·시간은 마감
- 자격(§4): 비대상·무판정·영구제한은 403 — 시간표 자체를 못 본다
- 쿼리 수: 날짜×슬롯이 늘어도 고정(N+1 회귀 방지)

시간 의미론: apps.clinic.booking.timezone.now 를 patch 해 고정(Asia/Seoul).
기준일 2026-07-22 은 수요일이자 시험일 → 창구는 7/23(목)~7/27(월).
(모델 요일 축 0=일…6=토 → 월=1, 수=3, 목=4, 금=5)
"""
import datetime
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import Student, User
from apps.grades.models import Exam

from .models import ClinicEligibility, ClinicRequest, ClinicSlot

PASSWORD = "pw-Secret-77!"
URL = "/api/student/clinic/availability"

TODAY = datetime.date(2026, 7, 22)  # 수 = 시험일
THU = datetime.date(2026, 7, 23)  # 창구 첫날
MON_END = datetime.date(2026, 7, 27)  # 창구 끝

NOW = timezone.make_aware(datetime.datetime(2026, 7, 22, 7, 0))
NOW_0800 = timezone.make_aware(datetime.datetime(2026, 7, 22, 8, 0))
NOW_2300 = timezone.make_aware(datetime.datetime(2026, 7, 22, 23, 0))
NOW_ON_END = timezone.make_aware(datetime.datetime(2026, 7, 27, 7, 0))
NOW_AFTER_END = timezone.make_aware(datetime.datetime(2026, 7, 30, 7, 0))

# 오늘 하루 어느 시각이든 결과가 같아야 한다(옛 08:00 경계가 사라졌다는 증거).
ALL_DAY = (NOW, NOW_0800, NOW_2300)


def freeze_now(at=NOW):
    return mock.patch("apps.clinic.booking.timezone.now", return_value=at)


def make_student(login_id, name):
    user = User.objects.create_user(
        login_id=login_id, password=PASSWORD, name=name, role=User.Role.STUDENT
    )
    return Student.objects.create(
        user=user,
        matching_key=f"uid-{login_id}",
        enrollment_status=Student.EnrollmentStatus.REGISTERED,
    )


class AvailabilityFixtureMixin:
    """목 2타임 + 월 1타임 + 수 1타임(창구 밖) + 금 1타임(비활성).

    창구(7/23~7/27) 안에서 시간이 뜨는 날은 목 7/23 과 월 7/27 뿐이다 —
    금 7/24 는 슬롯이 폐지, 토·일은 슬롯 없음, 수 7/29 는 창구 밖.
    """

    @classmethod
    def setUpTestData(cls):
        cls.exam = Exam.objects.create(name="7월 모의고사", exam_date=TODAY)
        cls.thu_19 = ClinicSlot.objects.create(
            weekday=4, start_time=datetime.time(19, 0), end_time=datetime.time(20, 0)
        )
        cls.thu_20 = ClinicSlot.objects.create(
            weekday=4, start_time=datetime.time(20, 0), end_time=datetime.time(21, 0)
        )
        cls.mon_19 = ClinicSlot.objects.create(
            weekday=1, start_time=datetime.time(19, 0), end_time=datetime.time(20, 0)
        )
        cls.wed_19 = ClinicSlot.objects.create(
            weekday=3, start_time=datetime.time(19, 0), end_time=datetime.time(20, 0)
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


# dev 의 테스트용 구멍과 무관하게 운영 규칙을 고정한다
@override_settings(CLINIC_ALLOW_SAME_DAY=False)
class ClinicAvailabilityTests(AvailabilityFixtureMixin, TestCase):
    def setUp(self):
        self.client.force_login(self.s_target.user)

    # --- 날짜 축 ----------------------------------------------------------

    def test_default_range_is_tomorrow_through_window_end(self):
        body = self.fetch().json()
        self.assertEqual(body["exam_id"], self.exam.exam_id)
        self.assertEqual(body["range"], {"from": "2026-07-23", "to": "2026-07-28"})
        dates = [d["date"] for d in body["days"]]
        # 창구 안에서 활성 슬롯이 있는 날만 — 금은 폐지, 토·일·화는 슬롯 없음.
        # 창구 끝 7/28(화)이 range 에는 들어 있으나 그 요일 슬롯이 없어 날짜로는
        # 안 뜬다 — 창구 끝 날짜가 실제로 뜨는 것은 SaturdayExamWindowTests 가 본다.
        self.assertEqual(dates, ["2026-07-23", "2026-07-27"])
        self.assertEqual(body["days"][0]["weekday"], 4)

    def test_day_lists_active_times_of_that_weekday(self):
        day = self.days_by_date()["2026-07-23"]
        self.assertEqual(
            day["times"],
            [
                {
                    "slot_id": self.thu_19.slot_id,
                    "start_time": "19:00",
                    "end_time": "20:00",
                    "available": True,
                    "reason": None,
                },
                {
                    "slot_id": self.thu_20.slot_id,
                    "start_time": "20:00",
                    "end_time": "21:00",
                    "available": True,
                    "reason": None,
                },
            ],
        )
        self.assertEqual(len(self.days_by_date()["2026-07-27"]["times"]), 1)

    def test_inactive_slot_never_appears(self):
        # 금 7/24 는 창구 안이지만 슬롯이 폐지(is_active=false)라 존재 자체를 감춘다
        self.assertNotIn("2026-07-24", set(self.days_by_date()))

    def test_days_without_active_slot_are_omitted(self):
        dates = set(self.days_by_date())
        self.assertNotIn("2026-07-25", dates)  # 토
        self.assertNotIn("2026-07-26", dates)  # 일

    def test_past_dates_are_clamped_to_tomorrow(self):
        body = self.fetch(**{"from": "2026-07-01", "to": "2026-07-23"}).json()
        self.assertEqual(body["range"], {"from": "2026-07-23", "to": "2026-07-23"})
        self.assertEqual([d["date"] for d in body["days"]], ["2026-07-23"])

    def test_today_is_never_offered(self):
        for at in ALL_DAY:
            body = self.fetch(at=at).json()
            self.assertEqual(body["range"]["from"], "2026-07-23", at)
            self.assertNotIn("2026-07-22", {d["date"] for d in body["days"]}, at)

    def test_today_is_dropped_even_when_asked_for_explicitly(self):
        for at in ALL_DAY:
            body = self.fetch(at=at, **{"from": "2026-07-22", "to": "2026-07-23"}).json()
            self.assertEqual(body["range"]["from"], "2026-07-23", at)
            self.assertEqual([d["date"] for d in body["days"]], ["2026-07-23"], at)

    def test_fully_past_range_returns_no_days(self):
        body = self.fetch(**{"from": "2026-07-01", "to": "2026-07-10"}).json()
        self.assertEqual(body["days"], [])

    # --- 창구 끝 ----------------------------------------------------------

    def test_far_range_is_clamped_to_the_window_end(self):
        body = self.fetch(**{"from": "2026-07-23", "to": "2026-12-31"}).json()
        self.assertEqual(body["range"], {"from": "2026-07-23", "to": "2026-07-28"})
        dates = {d["date"] for d in body["days"]}
        # 활성 슬롯이 있는 요일이어도 창구 밖 날짜는 뜨지 않는다
        self.assertNotIn("2026-07-29", dates)  # 수 — 창구 끝 다음날
        self.assertNotIn("2026-07-30", dates)  # 목
        self.assertNotIn("2026-08-04", dates)  # 화 — 다음 주 같은 요일

    def test_from_only_ends_at_the_window_end(self):
        body = self.fetch(**{"from": "2026-07-25"}).json()
        self.assertEqual(body["range"], {"from": "2026-07-25", "to": "2026-07-28"})

    def test_range_entirely_after_the_window_returns_no_days(self):
        res = self.fetch(**{"from": "2026-08-01", "to": "2026-08-31"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["days"], [])

    def test_closed_window_returns_empty_days_not_403(self):
        # 자격은 그대로다 — 기간이 끝난 것이라 403(비대상)과 다른 사실이다
        for at in (NOW_ON_END, NOW_AFTER_END):
            res = self.fetch(at=at)
            self.assertEqual(res.status_code, 200, at)
            self.assertEqual(res.json()["days"], [], at)

    # --- 마감(정원 1) -----------------------------------------------------

    def test_single_active_request_closes_the_time(self):
        self.make_request_row(self.s_other, self.thu_19, THU)
        days = self.days_by_date()
        times = {t["slot_id"]: t for t in days["2026-07-23"]["times"]}
        closed = times[self.thu_19.slot_id]
        self.assertFalse(closed["available"])
        self.assertEqual(closed["reason"], "마감")
        # 같은 날 다른 시간은 그대로 열려 있다
        self.assertTrue(times[self.thu_20.slot_id]["available"])
        # 다른 날짜의 슬롯도 영향 없다
        self.assertTrue(days["2026-07-27"]["times"][0]["available"])

    def test_approved_request_also_closes(self):
        self.make_request_row(
            self.s_other, self.mon_19, MON_END, status=ClinicRequest.Status.APPROVED
        )
        times = {t["slot_id"]: t for t in self.days_by_date()["2026-07-27"]["times"]}
        self.assertFalse(times[self.mon_19.slot_id]["available"])

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
        self.make_request_row(self.s_target, self.thu_19, THU)
        times = {t["slot_id"]: t for t in self.days_by_date()["2026-07-23"]["times"]}
        mine = times[self.thu_19.slot_id]
        self.assertFalse(mine["available"])
        self.assertEqual(mine["reason"], "내신청")

    # --- 구간 입력 --------------------------------------------------------

    def test_explicit_range(self):
        body = self.fetch(**{"from": "2026-07-23", "to": "2026-07-24"}).json()
        self.assertEqual(body["range"], {"from": "2026-07-23", "to": "2026-07-24"})
        self.assertEqual([d["date"] for d in body["days"]], ["2026-07-23"])

    def test_reversed_range_400(self):
        self.assertEqual(
            self.fetch(**{"from": "2026-07-27", "to": "2026-07-23"}).status_code, 400
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
            self.assertEqual(self.fetch().status_code, 403, student.matching_key)

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
        self.make_request_row(self.s_other, self.thu_19, THU)
        self.make_request_row(self.s_none, self.mon_19, MON_END)
        # 세션 2 + 학생 1 + 시험 1 + 자격 1 + 슬롯 1 + 예약현황 집계 1
        with freeze_now(), self.assertNumQueries(7):
            self.client.get(URL, {"exam_id": self.exam.exam_id})
        # 구간을 아무리 늘려도 쿼리 수는 그대로 — 날짜×슬롯 루프에 쿼리 없음
        with freeze_now(), self.assertNumQueries(7):
            self.client.get(
                URL,
                {"exam_id": self.exam.exam_id, "from": "2026-07-22", "to": "2026-12-31"},
            )


# dev 의 테스트용 구멍과 무관하게 운영 규칙을 고정한다
@override_settings(CLINIC_ALLOW_SAME_DAY=False)
class WindowNarrowsDayByDayTests(TestCase):
    """창구는 시험일 + 6일로 고정이고, 날이 갈수록 남은 날짜만 줄어든다.

    2026-07-30 대표 확정("다음 수업 전날까지") 이후 **요일 경계는 사라졌다** —
    어느 요일에 시험을 봐도 창구 길이가 같다. 여기서 보는 것은 창구가 닫히는
    게 아니라 **앞쪽(당일 불가)이 밀어 올려 남은 날짜가 줄어드는** 모습이다.

    토요일 시험 8/1 → 창구 끝 8/7(금). 슬롯은 일·월·화·수만 활성이라
    목·금은 창구 안이어도 날짜로 뜨지 않는다.
    """

    SAT = timezone.make_aware(datetime.datetime(2026, 8, 1, 7, 0))  # 시험 당일
    SUN = timezone.make_aware(datetime.datetime(2026, 8, 2, 7, 0))
    TUE = timezone.make_aware(datetime.datetime(2026, 8, 4, 7, 0))
    LAST = timezone.make_aware(datetime.datetime(2026, 8, 7, 7, 0))  # 창구 끝 당일

    @classmethod
    def setUpTestData(cls):
        cls.exam = Exam.objects.create(
            name="8월 토요 모의고사", exam_date=datetime.date(2026, 8, 1)
        )
        for weekday in (0, 1, 2, 3):  # 일·월·화·수 (목·금·토는 슬롯 없음)
            ClinicSlot.objects.create(
                weekday=weekday,
                start_time=datetime.time(19, 0),
                end_time=datetime.time(20, 0),
            )
        cls.student = make_student("sat-1", "토요일")
        ClinicEligibility.objects.create(exam=cls.exam, student=cls.student, is_target=True)

    def dates(self, at):
        with freeze_now(at):
            res = self.client.get(URL, {"exam_id": self.exam.exam_id})
        self.assertEqual(res.status_code, 200, res.content)
        return [d["date"] for d in res.json()["days"]]

    def setUp(self):
        self.client.force_login(self.student.user)

    def test_on_exam_day_the_whole_window_is_open(self):
        # 창구 8/2~8/7 중 슬롯이 있는 날만
        self.assertEqual(
            self.dates(self.SAT),
            ["2026-08-02", "2026-08-03", "2026-08-04", "2026-08-05"],
        )

    def test_the_front_edge_moves_up_each_day(self):
        self.assertEqual(self.dates(self.SUN), ["2026-08-03", "2026-08-04", "2026-08-05"])
        self.assertEqual(self.dates(self.TUE), ["2026-08-05"])

    def test_on_the_window_end_nothing_remains(self):
        # 창구 끝 당일에는 잡을 수 있는 **내일**이 창구 밖이다
        self.assertEqual(self.dates(self.LAST), [])

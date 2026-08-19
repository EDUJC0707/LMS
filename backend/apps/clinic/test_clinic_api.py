"""클리닉 신청 API 4차 슬라이스 테스트 — PRD 3.2.4 결정 전부 강제.

검증 축:
- 자격(§4): 대상자(is_target)만 신청 가능. 비대상·무판정은 미대상 표시만,
  신청은 403. 날짜별 가용 시간은 별도 API(test_clinic_availability_api)
- 정원 **1 고정**(2026-07-21 회의): 활성 신청(대기+승인배정)이 한 건만 있어도
  그 날짜·시간은 마감 400. 취소·미승인은 집계 제외.
  동시성은 select_for_update(경합 테스트 — 정원 1 이라 더 중요해졌다)
- **신청 창구**(2026-07-29 확정): 내일 ~ **시험 주 다음 월요일**까지만.
  당일·지난 날짜는 시각과 무관하게 차단(앞쪽 끝), 창구 끝 다음날부터 차단
  (뒤쪽 끝). API 직접 호출도 같은 게이트를 통과해야 한다
- 노쇼 영구제한: clinic_banned=true → 신청·변경 403 (취소는 허용)
- 중복 활성 신청 400 / 본인 것만 수정·취소(타인 404)
- 취소는 노쇼로 집계하지 않음(noshow_count·clinic_banned 불변) + **창구와 무관**
- 링크: 시작 5분 전부터만 conference_url 노출(link_active)

시간 의미론: apps.clinic.booking.timezone.now 를 patch 해 고정(Asia/Seoul —
attendance_admin 테스트 선례).

날짜 축(기준일 2026-07-22 = 수요일, 모델 요일 0=일…6=토):
  시험일 = 오늘(수 7/22 — 시험은 수업 중에 본다) → 창구 끝 = 7/27(월).
  신청 가능 날짜는 7/23(목)~7/27(월) 뿐이며, 창구가 한 주보다 짧으므로
  **같은 요일은 창구 안에 두 번 오지 않는다**(슬롯 하나당 날짜 하나).
"""
import datetime
import json
import threading
from unittest import mock

from django.db import connection
from django.test import SimpleTestCase, TestCase, TransactionTestCase
from django.utils import timezone

from apps.accounts.models import Student, User
from apps.grades.models import Exam

from . import booking
from .models import ClinicEligibility, ClinicRequest, ClinicSlot

PASSWORD = "pw-Secret-77!"
CLINIC_URL = "/api/student/clinic"
REQUESTS_URL = "/api/student/clinic/requests"

# 2026-07-22 = 수요일. 모델 요일 축: 0=일…6=토 → 월=1, 화=2, 수=3, 목=4, 금=5, 토=6.
TODAY = datetime.date(2026, 7, 22)  # 시험일 = 오늘(당일이라 신청 불가)
THU = datetime.date(2026, 7, 23)  # 창구 첫날(내일)
FRI = datetime.date(2026, 7, 24)
SAT = datetime.date(2026, 7, 25)  # 비활성 슬롯 요일
MON_LAST_APPLY = datetime.date(2026, 7, 27)  # 창구 끝의 전날 = 신청 마감일
TUE_END = datetime.date(2026, 7, 28)  # 창구 끝 = 받을 수 있는 마지막 클리닉(화)
WED_AFTER = datetime.date(2026, 7, 29)  # 창구 끝 다음날 — 여기서부터 닫힌다
NEXT_TUE = datetime.date(2026, 8, 4)  # 창구 끝의 다음 주 같은 요일 — 한참 밖
PAST_WED = datetime.date(2026, 7, 15)

NOW = timezone.make_aware(datetime.datetime(2026, 7, 22, 7, 0))
NOW_0800 = timezone.make_aware(datetime.datetime(2026, 7, 22, 8, 0))
NOW_2300 = timezone.make_aware(datetime.datetime(2026, 7, 22, 23, 0))
NOW_1854 = timezone.make_aware(datetime.datetime(2026, 7, 22, 18, 54))
NOW_1855 = timezone.make_aware(datetime.datetime(2026, 7, 22, 18, 55))
# 창구 끝 당일·그 이후 — 이 시점부터는 잡을 수 있는 날짜가 하나도 없다.
NOW_ON_END = timezone.make_aware(datetime.datetime(2026, 7, 27, 7, 0))
NOW_AFTER_END = timezone.make_aware(datetime.datetime(2026, 7, 28, 7, 0))

# 오늘 하루 어느 시각이든 결과가 같아야 한다(옛 08:00 경계가 사라졌다는 증거).
ALL_DAY = (NOW, NOW_0800, NOW_2300)

OUT_OF_WINDOW = "클리닉 신청 기간 밖의 날짜입니다."


def freeze_now(at=NOW):
    """클리닉 서비스의 기준 시각 고정(서비스 모듈 경유 timezone.now 만 patch)."""
    return mock.patch("apps.clinic.booking.timezone.now", return_value=at)


def make_user(login_id, role, name="사용자"):
    return User.objects.create_user(login_id=login_id, password=PASSWORD, name=name, role=role)


def make_student(login_id, name):
    user = make_user(login_id, User.Role.STUDENT, name=name)
    return Student.objects.create(
        user=user, matching_key=f"uid-{login_id}",
        enrollment_status=Student.EnrollmentStatus.REGISTERED,
    )


class ClinicWindowTests(SimpleTestCase):
    """창구 끝 = **다음 수업 전날** = 시험일 + 6일 (2026-07-30 대표 확정).

    수업은 반별 주 1회라 다음 수업은 같은 요일 7일 뒤고, 클리닉은 그 전에
    끝나야 한다. **요일로 못 박지 않는다** — 반마다 수업 요일이 다르므로
    고정 요일은 특정 반에서만 맞는다(월요일·화요일로 두 번 잡았다가 두 번
    어긋났다). 신청 마감(클리닉 날짜의 전날)은 `_check_date_open` 소관이다.
    """

    def test_wednesday_class_closes_on_tuesday(self):
        # 대표 예시: 수요반 시험 7/29(수) → 마지막 클리닉 8/4(화)
        self.assertEqual(
            booking.booking_window_end(datetime.date(2026, 7, 29)),
            datetime.date(2026, 8, 4),
        )

    def test_thursday_class_closes_on_wednesday(self):
        # 대표 예시: 목요반 시험 7/30(목) → 마지막 클리닉 8/5(수)
        self.assertEqual(
            booking.booking_window_end(datetime.date(2026, 7, 30)),
            datetime.date(2026, 8, 5),
        )

    def test_saturday_class_closes_on_friday(self):
        self.assertEqual(
            booking.booking_window_end(datetime.date(2026, 8, 1)),
            datetime.date(2026, 8, 7),
        )

    def test_end_is_always_the_day_before_the_next_class(self):
        start = datetime.date(2026, 7, 20)
        for offset in range(14):
            exam_date = start + datetime.timedelta(days=offset)
            end = booking.booking_window_end(exam_date)
            # 다음 수업(같은 요일 7일 뒤)의 전날 — 요일이 아니라 간격이 기준
            self.assertEqual(end, exam_date + datetime.timedelta(days=6), exam_date)
            self.assertNotEqual(
                booking.model_weekday(end), booking.model_weekday(exam_date), exam_date
            )


class ClinicFixtureMixin:
    """시험(오늘) + 월·화·수·목·금 슬롯(토는 비활성) · 대상/비대상/무판정/제한 학생.

    창구(7/23~7/27) 안: 목 7/23 · 금 7/24 · 월 7/27.
    창구 밖: 화 7/28 · 수 7/29(그리고 오늘 7/22 는 당일이라 앞쪽에서 막힌다).
    """

    @classmethod
    def setUpTestData(cls):
        cls.exam = Exam.objects.create(name="7월 모의고사", exam_date=TODAY)
        cls.slot_mon = ClinicSlot.objects.create(
            weekday=1, start_time=datetime.time(19, 0), end_time=datetime.time(20, 0),
        )
        cls.slot_tue = ClinicSlot.objects.create(
            weekday=2, start_time=datetime.time(19, 0), end_time=datetime.time(20, 0),
        )
        cls.slot_wed = ClinicSlot.objects.create(
            weekday=3, start_time=datetime.time(19, 0), end_time=datetime.time(20, 0),
        )
        cls.slot_thu = ClinicSlot.objects.create(
            weekday=4, start_time=datetime.time(19, 0), end_time=datetime.time(20, 0),
        )
        cls.slot_fri = ClinicSlot.objects.create(
            weekday=5, start_time=datetime.time(19, 0), end_time=datetime.time(20, 0),
        )
        cls.slot_off = ClinicSlot.objects.create(
            weekday=6, start_time=datetime.time(19, 0), end_time=datetime.time(20, 0),
            is_active=False,
        )
        cls.s_target = make_student("cl-1", "박선호")
        cls.s_target2 = make_student("cl-2", "한지원")
        cls.s_not = make_student("cl-3", "오평균")
        cls.s_none = make_student("cl-4", "무기록")
        cls.s_banned = make_student("cl-5", "금지훈")
        cls.s_banned.clinic_banned = True
        cls.s_banned.noshow_count = 2
        cls.s_banned.save(update_fields=["clinic_banned", "noshow_count"])
        cls.parent_user = make_user("cl-par", User.Role.PARENT, name="학부모")
        for student in (cls.s_target, cls.s_target2, cls.s_banned):
            ClinicEligibility.objects.create(exam=cls.exam, student=student, is_target=True)
        ClinicEligibility.objects.create(
            exam=cls.exam, student=cls.s_not, is_target=False,
            reason=ClinicEligibility.Reason.ABOVE_AVG,
        )

    def login(self, user):
        self.client.force_login(user)

    def get_clinic(self, at=NOW, **params):
        with freeze_now(at):
            return self.client.get(CLINIC_URL, {"exam_id": self.exam.exam_id, **params})

    def post_booking(self, body, at=NOW):
        with freeze_now(at):
            return self.client.post(
                REQUESTS_URL, data=json.dumps(body), content_type="application/json"
            )

    def book(self, slot, requested_date, at=NOW, exam=None):
        exam = exam if exam is not None else self.exam
        return self.post_booking(
            {
                "exam_id": exam.exam_id,
                "slot_id": slot.slot_id,
                "requested_date": requested_date.isoformat(),
            },
            at=at,
        )

    def patch_booking(self, clinic_id, body, at=NOW):
        with freeze_now(at):
            return self.client.patch(
                f"{REQUESTS_URL}/{clinic_id}",
                data=json.dumps(body),
                content_type="application/json",
            )

    def cancel_booking(self, clinic_id, at=NOW):
        with freeze_now(at):
            return self.client.post(
                f"{REQUESTS_URL}/{clinic_id}/cancel", content_type="application/json"
            )

    def make_request_row(self, student, slot, requested_date,
                         status=ClinicRequest.Status.PENDING, **kwargs):
        return ClinicRequest.objects.create(
            student=student, exam=self.exam, slot=slot, requested_date=requested_date,
            requested_time=slot.start_time, status=status, **kwargs,
        )


class ClinicHomeTests(ClinicFixtureMixin, TestCase):
    """GET /api/student/clinic?exam_id= — 자격·내 신청 현황(슬롯 목록 없음)."""

    def test_target_sees_eligibility_only(self):
        self.login(self.s_target.user)
        res = self.get_clinic()
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["exam"]["exam_id"], self.exam.exam_id)
        self.assertEqual(body["exam"]["name"], "7월 모의고사")
        self.assertTrue(body["eligibility"]["is_target"])
        self.assertIsNone(body["eligibility"]["reason"])
        self.assertFalse(body["clinic_banned"])
        self.assertEqual(body["my_requests"], [])
        # 슬롯 목록은 날짜 축 API(/availability)로 이관 — 여기엔 없다
        self.assertNotIn("slots", body)

    def test_non_target_sees_reason(self):
        self.login(self.s_not.user)
        body = self.get_clinic().json()
        self.assertFalse(body["eligibility"]["is_target"])
        self.assertEqual(body["eligibility"]["reason"], "평균이상")
        self.assertNotIn("slots", body)

    def test_no_eligibility_row_treated_as_non_target(self):
        self.login(self.s_none.user)
        body = self.get_clinic().json()
        self.assertFalse(body["eligibility"]["is_target"])
        self.assertIsNone(body["eligibility"]["reason"])

    def test_banned_target_is_flagged(self):
        self.login(self.s_banned.user)
        body = self.get_clinic().json()
        self.assertTrue(body["eligibility"]["is_target"])
        self.assertTrue(body["clinic_banned"])

    def test_my_requests_and_link_gating(self):
        req = self.make_request_row(
            self.s_target, self.slot_wed, TODAY,
            status=ClinicRequest.Status.APPROVED,
            conference_url="https://meet.google.com/abc-defg-hij",
        )
        self.login(self.s_target.user)
        before = self.get_clinic(at=NOW_1854).json()["my_requests"]
        self.assertEqual(len(before), 1)
        row = before[0]
        self.assertEqual(row["clinic_id"], req.clinic_id)
        self.assertEqual(row["status"], "승인배정")
        self.assertEqual(row["requested_date"], "2026-07-22")
        self.assertEqual(row["requested_time"], "19:00")
        self.assertFalse(row["link_active"])
        self.assertIsNone(row["conference_url"])  # 시작 5분 전까지 URL 미노출
        after = self.get_clinic(at=NOW_1855).json()["my_requests"][0]
        self.assertTrue(after["link_active"])
        self.assertEqual(after["conference_url"], "https://meet.google.com/abc-defg-hij")

    def test_pending_request_has_no_link(self):
        self.make_request_row(self.s_target, self.slot_wed, TODAY)
        self.login(self.s_target.user)
        row = self.get_clinic(at=NOW_1855).json()["my_requests"][0]
        self.assertEqual(row["status"], "대기")
        self.assertFalse(row["link_active"])
        self.assertIsNone(row["conference_url"])

    def test_exam_id_required_and_validated(self):
        self.login(self.s_target.user)
        with freeze_now():
            self.assertEqual(self.client.get(CLINIC_URL).status_code, 400)
            self.assertEqual(
                self.client.get(CLINIC_URL, {"exam_id": "abc"}).status_code, 400
            )
            self.assertEqual(
                self.client.get(CLINIC_URL, {"exam_id": 999999}).status_code, 404
            )

    def test_role_gates(self):
        self.assertEqual(self.client.get(CLINIC_URL).status_code, 403)
        self.login(self.parent_user)
        self.assertEqual(self.client.get(CLINIC_URL).status_code, 403)


class ClinicBookingCreateTests(ClinicFixtureMixin, TestCase):
    """POST /api/student/clinic/requests — 자격·정원·창구·노쇼·중복 강제."""

    def setUp(self):
        self.login(self.s_target.user)

    def test_create_booking(self):
        res = self.book(self.slot_thu, THU)
        self.assertEqual(res.status_code, 201)
        req = ClinicRequest.objects.get(student=self.s_target)
        self.assertEqual(req.status, ClinicRequest.Status.PENDING)
        self.assertEqual(req.exam_id, self.exam.exam_id)
        self.assertEqual(req.slot_id, self.slot_thu.slot_id)
        self.assertEqual(req.requested_date, THU)
        self.assertEqual(req.requested_time, datetime.time(19, 0))
        body = res.json()
        self.assertEqual(body["request"]["clinic_id"], req.clinic_id)
        self.assertEqual(body["request"]["status"], "대기")
        self.assertEqual(body["request"]["requested_date"], "2026-07-23")
        self.assertEqual(body["request"]["requested_time"], "19:00")
        # 재조회 불필요 계약 — 확정된 슬롯 요약(정원·잔여석은 싣지 않는다)
        self.assertEqual(
            body["slot"],
            {
                "slot_id": self.slot_thu.slot_id,
                "weekday": 4,
                "start_time": "19:00",
                "end_time": "20:00",
            },
        )

    def test_one_active_request_closes_the_time(self):
        # 정원 1 고정(0721 회의) — 다른 학생 활성 신청 1건이면 곧바로 마감.
        # 창구가 한 주보다 짧아 같은 슬롯의 다른 날짜는 없다 — 마감의 범위가
        # (슬롯, 날짜)라는 사실은 다른 날짜·시간이 그대로 열려 있는 것으로 본다.
        self.make_request_row(self.s_target2, self.slot_thu, THU)
        self.assertEqual(self.book(self.slot_thu, THU).status_code, 400)
        self.assertEqual(self.book(self.slot_fri, FRI).status_code, 201)

    # --- 창구 앞쪽 끝(당일 불가) ------------------------------------------

    def test_today_400_at_every_hour(self):
        for at in ALL_DAY:
            res = self.book(self.slot_wed, TODAY, at=at)
            self.assertEqual(res.status_code, 400, at)
        self.assertFalse(ClinicRequest.objects.exists())

    def test_tomorrow_201_even_late_at_night(self):
        res = self.book(self.slot_thu, THU, at=NOW_2300)
        self.assertEqual(res.status_code, 201)

    def test_today_and_past_dates_say_which_one(self):
        self.assertEqual(
            self.book(self.slot_wed, TODAY, at=NOW_0800).json()["detail"],
            "오늘 클리닉은 신청·변경할 수 없습니다.",
        )
        self.assertEqual(
            self.book(self.slot_wed, PAST_WED).json()["detail"],
            "지난 날짜에는 신청·변경할 수 없습니다.",
        )

    def test_past_date_400(self):
        self.assertEqual(self.book(self.slot_wed, PAST_WED).status_code, 400)

    # --- 창구 뒤쪽 끝(시험 주 다음 월요일) --------------------------------

    def test_window_end_tuesday_is_open(self):
        self.assertEqual(self.book(self.slot_tue, TUE_END).status_code, 201)

    def test_day_after_window_end_400(self):
        res = self.book(self.slot_wed, WED_AFTER)
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()["detail"], OUT_OF_WINDOW)
        self.assertFalse(ClinicRequest.objects.exists())

    def test_date_far_beyond_window_400(self):
        self.assertEqual(self.book(self.slot_wed, WED_AFTER).status_code, 400)
        self.assertEqual(self.book(self.slot_tue, NEXT_TUE).status_code, 400)

    def test_today_inside_the_window_is_still_refused(self):
        # 오늘(7/22)은 창구 끝(7/27) 안쪽이지만 당일이라 막힌다 — 두 규칙이 함께
        # 걸리고, 먼저 걸리는 쪽(당일)의 사실을 말한다.
        res = self.book(self.slot_wed, TODAY)
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()["detail"], "오늘 클리닉은 신청·변경할 수 없습니다.")

    def test_nothing_is_bookable_once_the_window_closed(self):
        # 창구 끝 당일(화)에는 내일(수)부터가 이미 창구 밖 — 잡을 날짜가 없다.
        # 각 시점에서 **아직 오지 않은** 날짜만 본다(오늘·과거는 앞쪽 끝이
        # 먼저 잡아 다른 사실을 말한다).
        for at, dates in (
            (NOW_ON_END, ((self.slot_wed, WED_AFTER), (self.slot_tue, NEXT_TUE))),
            (NOW_AFTER_END, ((self.slot_wed, WED_AFTER), (self.slot_tue, NEXT_TUE))),
        ):
            for slot, date in dates:
                res = self.book(slot, date, at=at)
                self.assertEqual(res.status_code, 400, (at, date))
                self.assertEqual(res.json()["detail"], OUT_OF_WINDOW, (at, date))
        self.assertFalse(ClinicRequest.objects.exists())

    # --- 나머지 규칙 ------------------------------------------------------

    def test_weekday_mismatch_400(self):
        self.assertEqual(self.book(self.slot_thu, FRI).status_code, 400)

    def test_non_target_403(self):
        for student in (self.s_not, self.s_none):
            self.login(student.user)
            res = self.book(self.slot_thu, THU)
            self.assertEqual(res.status_code, 403, student.matching_key)
        self.assertFalse(ClinicRequest.objects.exists())

    def test_banned_403(self):
        self.login(self.s_banned.user)
        self.assertEqual(self.book(self.slot_thu, THU).status_code, 403)

    def test_full_slot_400(self):
        blocker = self.make_request_row(self.s_target2, self.slot_thu, THU)
        self.assertEqual(self.book(self.slot_thu, THU).status_code, 400)
        blocker.status = ClinicRequest.Status.APPROVED
        blocker.save(update_fields=["status"])
        self.assertEqual(self.book(self.slot_thu, THU).status_code, 400)
        # 취소는 정원 집계에서 빠진다 — 다시 열림
        blocker.status = ClinicRequest.Status.CANCELLED
        blocker.save(update_fields=["status"])
        self.assertEqual(self.book(self.slot_thu, THU).status_code, 201)

    def test_duplicate_active_400(self):
        self.make_request_row(self.s_target, self.slot_thu, THU)
        self.assertEqual(self.book(self.slot_fri, FRI).status_code, 400)

    def test_cancelled_request_does_not_block_new_booking(self):
        self.make_request_row(
            self.s_target, self.slot_thu, THU, status=ClinicRequest.Status.CANCELLED
        )
        self.assertEqual(self.book(self.slot_fri, FRI).status_code, 201)

    def test_invalid_body_400(self):
        for body in (
            {},
            {"exam_id": self.exam.exam_id, "slot_id": self.slot_thu.slot_id},
            {"exam_id": self.exam.exam_id, "requested_date": "2026-07-23"},
            {"exam_id": "x", "slot_id": self.slot_thu.slot_id, "requested_date": "2026-07-23"},
            {
                "exam_id": self.exam.exam_id,
                "slot_id": self.slot_thu.slot_id,
                "requested_date": "07/23/2026",
            },
        ):
            self.assertEqual(self.post_booking(body).status_code, 400, body)

    def test_unknown_or_inactive_slot_404(self):
        self.assertEqual(self.book(self.slot_off, SAT).status_code, 404)
        res = self.post_booking(
            {
                "exam_id": self.exam.exam_id,
                "slot_id": 999999,
                "requested_date": THU.isoformat(),
            }
        )
        self.assertEqual(res.status_code, 404)

    def test_unknown_exam_404(self):
        res = self.post_booking(
            {
                "exam_id": 999999,
                "slot_id": self.slot_thu.slot_id,
                "requested_date": THU.isoformat(),
            }
        )
        self.assertEqual(res.status_code, 404)

    def test_role_gates(self):
        self.client.logout()
        self.assertEqual(self.book(self.slot_thu, THU).status_code, 403)
        self.login(self.parent_user)
        self.assertEqual(self.book(self.slot_thu, THU).status_code, 403)


class ClinicBookingChangeTests(ClinicFixtureMixin, TestCase):
    """PATCH /api/student/clinic/requests/{id} — 같은 규칙 재검증 + 본인 것만."""

    def setUp(self):
        self.login(self.s_target.user)
        self.req = self.make_request_row(self.s_target, self.slot_tue, TUE_END)

    def test_change_slot_and_date(self):
        res = self.patch_booking(
            self.req.clinic_id,
            {"slot_id": self.slot_fri.slot_id, "requested_date": FRI.isoformat()},
        )
        self.assertEqual(res.status_code, 200)
        self.req.refresh_from_db()
        self.assertEqual(self.req.requested_date, FRI)
        self.assertEqual(self.req.status, ClinicRequest.Status.PENDING)
        self.assertEqual(self.req.updated_at, NOW)  # 시간수정 추적 스탬프
        self.assertEqual(res.json()["request"]["requested_date"], "2026-07-24")

    def test_change_slot_resets_approval(self):
        staff = make_user("cl-staff", User.Role.ASSISTANT, name="조교")
        self.req.status = ClinicRequest.Status.APPROVED
        self.req.assigned_staff = staff
        self.req.conference_url = "https://meet.google.com/xyz"
        self.req.save(update_fields=["status", "assigned_staff", "conference_url"])
        res = self.patch_booking(
            self.req.clinic_id,
            {"slot_id": self.slot_thu.slot_id, "requested_date": THU.isoformat()},
        )
        self.assertEqual(res.status_code, 200)
        self.req.refresh_from_db()
        self.assertEqual(self.req.slot_id, self.slot_thu.slot_id)
        self.assertEqual(self.req.requested_date, THU)
        self.assertEqual(self.req.requested_time, datetime.time(19, 0))
        # 시간 변경은 재승인 대상 — 배정·링크 회수(링크 재사용 금지)
        self.assertEqual(self.req.status, ClinicRequest.Status.PENDING)
        self.assertIsNone(self.req.assigned_staff)
        self.assertIsNone(self.req.conference_url)

    def test_change_away_from_today_400_at_every_hour(self):
        req = self.make_request_row(self.s_target2, self.slot_wed, TODAY)
        self.login(self.s_target2.user)
        for at in ALL_DAY:
            res = self.patch_booking(
                req.clinic_id,
                {"slot_id": self.slot_fri.slot_id, "requested_date": FRI.isoformat()},
                at=at,
            )
            self.assertEqual(res.status_code, 400, at)
        req.refresh_from_db()
        self.assertEqual(req.requested_date, TODAY)

    def test_change_onto_today_400_at_every_hour(self):
        for at in ALL_DAY:
            res = self.patch_booking(
                self.req.clinic_id,
                {"slot_id": self.slot_wed.slot_id, "requested_date": TODAY.isoformat()},
                at=at,
            )
            self.assertEqual(res.status_code, 400, at)

    def test_change_onto_tomorrow_200_even_late_at_night(self):
        res = self.patch_booking(
            self.req.clinic_id,
            {"slot_id": self.slot_thu.slot_id, "requested_date": THU.isoformat()},
            at=NOW_2300,
        )
        self.assertEqual(res.status_code, 200)

    def test_change_onto_window_end_tuesday_200(self):
        req = self.make_request_row(self.s_target2, self.slot_thu, THU)
        self.login(self.s_target2.user)
        # 창구 끝은 setUp 의 s_target 신청이 잡고 있다 — 비켜 준 뒤 옮긴다
        self.req.status = ClinicRequest.Status.CANCELLED
        self.req.save(update_fields=["status"])
        res = self.patch_booking(
            req.clinic_id,
            {"slot_id": self.slot_tue.slot_id, "requested_date": TUE_END.isoformat()},
        )
        self.assertEqual(res.status_code, 200)

    def test_change_onto_day_after_window_end_400(self):
        res = self.patch_booking(
            self.req.clinic_id,
            {"slot_id": self.slot_wed.slot_id, "requested_date": WED_AFTER.isoformat()},
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()["detail"], OUT_OF_WINDOW)
        self.req.refresh_from_db()
        self.assertEqual(self.req.requested_date, TUE_END)

    def test_change_onto_same_weekday_next_week_400(self):
        # 슬롯 요일은 맞지만 그 다음 주 화요일은 창구 밖이다
        res = self.patch_booking(
            self.req.clinic_id, {"requested_date": NEXT_TUE.isoformat()}
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()["detail"], OUT_OF_WINDOW)

    def test_change_to_full_slot_400(self):
        self.make_request_row(self.s_target2, self.slot_thu, THU)
        res = self.patch_booking(
            self.req.clinic_id,
            {"slot_id": self.slot_thu.slot_id, "requested_date": THU.isoformat()},
        )
        self.assertEqual(res.status_code, 400)

    def test_change_excludes_self_from_capacity(self):
        # 정원 1 슬롯에 그대로 머무르는 변경 — 본인 신청이 정원을 막지 않는다
        res = self.patch_booking(self.req.clinic_id, {"slot_id": self.slot_tue.slot_id})
        self.assertEqual(res.status_code, 200)

    def test_change_weekday_mismatch_400(self):
        res = self.patch_booking(self.req.clinic_id, {"requested_date": FRI.isoformat()})
        self.assertEqual(res.status_code, 400)

    def test_change_others_request_404(self):
        other = self.make_request_row(self.s_target2, self.slot_thu, THU)
        res = self.patch_booking(other.clinic_id, {"requested_date": FRI.isoformat()})
        self.assertEqual(res.status_code, 404)

    def test_change_cancelled_request_400(self):
        self.req.status = ClinicRequest.Status.CANCELLED
        self.req.save(update_fields=["status"])
        res = self.patch_booking(
            self.req.clinic_id,
            {"slot_id": self.slot_fri.slot_id, "requested_date": FRI.isoformat()},
        )
        self.assertEqual(res.status_code, 400)

    def test_change_requires_some_field(self):
        self.assertEqual(self.patch_booking(self.req.clinic_id, {}).status_code, 400)
        res = self.patch_booking(self.req.clinic_id, {"requested_date": "bad-date"})
        self.assertEqual(res.status_code, 400)
        res = self.patch_booking(self.req.clinic_id, {"slot_id": 999999})
        self.assertEqual(res.status_code, 404)

    def test_change_banned_403(self):
        req = self.make_request_row(self.s_banned, self.slot_thu, THU)
        self.login(self.s_banned.user)
        res = self.patch_booking(
            req.clinic_id,
            {"slot_id": self.slot_fri.slot_id, "requested_date": FRI.isoformat()},
        )
        self.assertEqual(res.status_code, 403)


class ClinicBookingCancelTests(ClinicFixtureMixin, TestCase):
    """POST /api/student/clinic/requests/{id}/cancel — 취소는 노쇼가 아니다."""

    def setUp(self):
        self.login(self.s_target.user)
        self.req = self.make_request_row(self.s_target, self.slot_tue, TUE_END)

    def test_cancel_pending(self):
        res = self.cancel_booking(self.req.clinic_id)
        self.assertEqual(res.status_code, 200)
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, ClinicRequest.Status.CANCELLED)
        self.assertEqual(self.req.cancelled_at, NOW)
        self.assertIsNone(self.req.attendance_status)
        # 취소는 clean — 노쇼 누적·영구제한에 영향 없다(PRD 3.2.4)
        self.s_target.refresh_from_db()
        self.assertEqual(self.s_target.noshow_count, 0)
        self.assertFalse(self.s_target.clinic_banned)
        self.assertEqual(res.json()["request"]["status"], "취소")

    def test_cancel_approved_is_clean(self):
        self.req.status = ClinicRequest.Status.APPROVED
        self.req.save(update_fields=["status"])
        res = self.cancel_booking(self.req.clinic_id)
        self.assertEqual(res.status_code, 200)
        self.s_target.refresh_from_db()
        self.assertEqual(self.s_target.noshow_count, 0)

    def test_cancel_twice_400(self):
        self.cancel_booking(self.req.clinic_id)
        self.assertEqual(self.cancel_booking(self.req.clinic_id).status_code, 400)

    def test_cancel_rejected_400(self):
        self.req.status = ClinicRequest.Status.REJECTED
        self.req.save(update_fields=["status"])
        self.assertEqual(self.cancel_booking(self.req.clinic_id).status_code, 400)

    def test_cancel_others_404(self):
        other = self.make_request_row(self.s_target2, self.slot_thu, THU)
        self.assertEqual(self.cancel_booking(other.clinic_id).status_code, 404)

    def test_cancel_today_is_a_noshow_at_every_hour(self):
        """당일 취소는 막지 않고 노쇼로 센다(FLOW 3-7) — 시각은 보지 않는다."""
        for at in ALL_DAY:
            req = self.make_request_row(self.s_target2, self.slot_wed, TODAY)
            self.login(self.s_target2.user)
            self.assertEqual(self.cancel_booking(req.clinic_id, at=at).status_code, 200, at)
            req.refresh_from_db()
            self.assertEqual(req.status, ClinicRequest.Status.CANCELLED)
            self.s_target2.refresh_from_db()
            self.assertEqual(self.s_target2.noshow_count, 1, at)
            # 다음 회를 위해 되돌린다 — 세는 것은 취소 1건당 1회다
            self.s_target2.noshow_count = 0
            self.s_target2.clinic_banned = False
            self.s_target2.save(update_fields=["noshow_count", "clinic_banned"])

    def test_cancel_past_date_is_a_noshow(self):
        """지나간 날짜도 같다 — 안 온 뒤에 무르는 것이라 더 무르지 않다."""
        req = self.make_request_row(self.s_target2, self.slot_wed, TODAY)
        self.login(self.s_target2.user)
        self.assertEqual(
            self.cancel_booking(req.clinic_id, at=NOW_AFTER_END).status_code, 200
        )
        self.s_target2.refresh_from_db()
        self.assertEqual(self.s_target2.noshow_count, 1)

    def test_second_same_day_cancel_bans(self):
        """노쇼 2회면 신청이 막힌다 — 조교가 찍은 결석과 같은 셈법이다."""
        self.login(self.s_target2.user)
        for _ in range(2):
            req = self.make_request_row(self.s_target2, self.slot_wed, TODAY)
            self.assertEqual(self.cancel_booking(req.clinic_id).status_code, 200)
        self.s_target2.refresh_from_db()
        self.assertEqual(self.s_target2.noshow_count, 2)
        self.assertTrue(self.s_target2.clinic_banned)

    def test_cancel_before_the_deadline_is_still_clean(self):
        """전날까지 무른 것은 그대로 깨끗하다 — 자리를 다시 채울 수 있었다."""
        req = self.make_request_row(self.s_target2, self.slot_thu, THU)
        self.login(self.s_target2.user)
        self.assertEqual(self.cancel_booking(req.clinic_id).status_code, 200)
        self.s_target2.refresh_from_db()
        self.assertEqual(self.s_target2.noshow_count, 0)
        self.assertFalse(self.s_target2.clinic_banned)

    def test_cancel_tomorrow_200_even_late_at_night(self):
        req = self.make_request_row(self.s_target2, self.slot_thu, THU)
        self.login(self.s_target2.user)
        self.assertEqual(self.cancel_booking(req.clinic_id, at=NOW_2300).status_code, 200)

    def test_cancel_is_not_gated_by_the_window(self):
        # 창구 밖 날짜로 잡혀 있는 예약(관리자·이관 데이터)도 무를 수 있다 —
        # 취소는 자원 반납이라 창구를 보지 않는다(신청·변경만 창구를 본다).
        req = self.make_request_row(self.s_target2, self.slot_wed, WED_AFTER)
        self.login(self.s_target2.user)
        self.assertEqual(self.cancel_booking(req.clinic_id).status_code, 200)
        req.refresh_from_db()
        self.assertEqual(req.status, ClinicRequest.Status.CANCELLED)

    def test_cancel_works_after_the_window_closed(self):
        req = self.make_request_row(self.s_target2, self.slot_wed, WED_AFTER)
        self.login(self.s_target2.user)
        # 창구가 닫힌 뒤(7/28)에도 아직 오지 않은 날짜는 무를 수 있다
        self.assertEqual(self.cancel_booking(req.clinic_id, at=NOW_AFTER_END).status_code, 200)

    def test_banned_student_can_still_cancel(self):
        req = self.make_request_row(self.s_banned, self.slot_thu, THU)
        self.login(self.s_banned.user)
        self.assertEqual(self.cancel_booking(req.clinic_id).status_code, 200)

    def test_role_gates(self):
        self.client.logout()
        self.assertEqual(self.cancel_booking(self.req.clinic_id).status_code, 403)


class ClinicBookingRaceTests(TransactionTestCase):
    """정원 경합 — select_for_update 슬롯 행 잠금으로 초과 신청 방지.

    정원 1 고정(2026-07-21 회의)으로 경합 창이 좁아진 만큼 결과는 더 치명적이다
    (2명이 같은 시간에 배정되면 조교·미트 스페이스가 하나뿐이라 운영이 깨진다).
    동시 신청 4건과 '신청 vs 변경' 교차 경합 둘 다 1건만 통과해야 한다.

    시각을 얼리지 않고 실제 now 로 돈다 — 시험일을 오늘로 두면 창구 끝(다음
    월요일)이 늘 미래라 당일·창구 규칙에 걸리지 않는다.
    """

    def setUp(self):
        today = timezone.localdate()
        self.exam = Exam.objects.create(name="경합시험", exam_date=today)
        self.target_date = booking.booking_window_end(today)  # 창구 끝(월) = 항상 미래
        weekday = booking.model_weekday(self.target_date)
        self.slot = ClinicSlot.objects.create(
            weekday=weekday, start_time=datetime.time(19, 0), end_time=datetime.time(20, 0),
        )
        self.other_slot = ClinicSlot.objects.create(
            weekday=weekday, start_time=datetime.time(20, 0), end_time=datetime.time(21, 0),
        )

    def make_targets(self, count):
        students = [make_student(f"race-{i}", f"경합{i}") for i in range(count)]
        for student in students:
            ClinicEligibility.objects.create(exam=self.exam, student=student, is_target=True)
        return students

    def run_concurrently(self, actions):
        """actions 를 동시에 실행하고 성공/마감 결과 목록을 돌려준다."""
        results = []
        barrier = threading.Barrier(len(actions), timeout=10)

        def run(action):
            try:
                barrier.wait()
                action()
                results.append("성공")
            except booking.ClinicError:
                results.append("마감")
            finally:
                connection.close()

        threads = [threading.Thread(target=run, args=(a,)) for a in actions]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)
        return results

    def booked_count(self):
        return ClinicRequest.objects.filter(
            slot=self.slot,
            requested_date=self.target_date,
            status__in=booking.ACTIVE_STATUSES,
        ).count()

    def test_concurrent_bookings_leave_exactly_one_winner(self):
        students = self.make_targets(4)
        results = self.run_concurrently(
            [
                (lambda s=s: booking.create_booking(
                    student=s, exam=self.exam, slot=self.slot,
                    requested_date=self.target_date,
                ))
                for s in students
            ]
        )
        self.assertEqual(sorted(results), ["마감", "마감", "마감", "성공"])
        self.assertEqual(self.booked_count(), 1)

    def test_change_racing_a_new_booking_cannot_double_book(self):
        mover, newcomer = self.make_targets(2)
        # mover 는 같은 날 다른 시간에 이미 신청해 두고 self.slot 으로 옮기려 한다
        existing = ClinicRequest.objects.create(
            student=mover, exam=self.exam, slot=self.other_slot,
            requested_date=self.target_date, requested_time=self.other_slot.start_time,
        )
        results = self.run_concurrently(
            [
                lambda: booking.change_booking(existing, self.slot, self.target_date),
                lambda: booking.create_booking(
                    student=newcomer, exam=self.exam, slot=self.slot,
                    requested_date=self.target_date,
                ),
            ]
        )
        self.assertEqual(sorted(results), ["마감", "성공"])
        self.assertEqual(self.booked_count(), 1)


class ClinicHistoryTests(ClinicFixtureMixin, TestCase):
    """지난 내역 — 회차를 고르지 않아도 한 목록으로 내려온다.

    화면에서 `대상 시험 선택` 드롭다운을 뺐다(2026-08-11 사용자 결정). 신청은
    지금 열린 회차 하나로만 하고, 지난 것은 회차 구분 없이 아래에 쌓인다.
    그러려면 응답이 **그 회차 것만** 담아서는 안 된다.
    """

    def setUp(self):
        self.client.force_login(self.s_target.user)

    def make(self, exam, date):
        return ClinicRequest.objects.create(
            student=self.s_target,
            exam=exam,
            slot=self.slot_wed,
            requested_date=date,
            requested_time=self.slot_wed.start_time,
        )

    def older_exam(self):
        return Exam.objects.create(name="6월 모의고사", exam_date=datetime.date(2026, 6, 10))

    def history(self):
        return self.client.get(
            CLINIC_URL, {"exam_id": self.exam.exam_id}
        ).json()["history"]

    def test_spans_other_exams(self):
        older = self.older_exam()
        self.make(older, datetime.date(2026, 6, 17))
        self.assertIn(older.exam_id, {row["exam_id"] for row in self.history()})

    def test_newest_first(self):
        self.make(self.older_exam(), datetime.date(2026, 6, 17))
        self.make(self.exam, datetime.date(2026, 7, 29))
        dates = [row["requested_date"] for row in self.history()]
        self.assertEqual(dates, sorted(dates, reverse=True))

    def test_carries_the_exam_name(self):
        # 회차 선택이 사라졌으니 어느 회차 것인지는 줄마다 붙어야 한다
        self.make(self.exam, datetime.date(2026, 7, 29))
        self.assertEqual(self.history()[0]["exam_name"], self.exam.name)

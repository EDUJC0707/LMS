"""클리닉 신청 API 4차 슬라이스 테스트 — PRD 3.2.4 결정 전부 강제.

검증 축:
- 자격(§4): 대상자(is_target)만 신청 가능. 비대상·무판정은 미대상 표시만,
  신청은 403. 날짜별 가용 시간은 별도 API(test_clinic_availability_api)
- 정원 **1 고정**(2026-07-21 회의): 활성 신청(대기+승인배정)이 한 건만 있어도
  그 날짜·시간은 마감 400. 취소·미승인은 집계 제외.
  동시성은 select_for_update(경합 테스트 — 정원 1 이라 더 중요해졌다)
- 당일 오전 8시 마감: 07:59/08:00 경계 — 신청·변경·취소 모두
- 노쇼 영구제한: clinic_banned=true → 신청·변경 403 (취소는 허용)
- 중복 활성 신청 400 / 본인 것만 수정·취소(타인 404)
- 취소는 노쇼로 집계하지 않음(noshow_count·clinic_banned 불변)
- 링크: 시작 5분 전부터만 meet_url 노출(link_active)

시간 의미론: apps.clinic.booking.timezone.now 를 patch 해 고정(Asia/Seoul —
attendance_admin 테스트 선례). 기준일 2026-07-22 은 수요일(weekday=3).
"""
import datetime
import json
import threading
from unittest import mock

from django.db import connection
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from apps.accounts.models import Student, User
from apps.grades.models import Exam

from . import booking
from .models import ClinicEligibility, ClinicRequest, ClinicSlot

PASSWORD = "pw-Secret-77!"
CLINIC_URL = "/api/student/clinic"
REQUESTS_URL = "/api/student/clinic/requests"

# 2026-07-22 = 수요일. 모델 요일 축: 0=일…6=토 → 수=3, 목=4.
TODAY = datetime.date(2026, 7, 22)
THU = datetime.date(2026, 7, 23)
NEXT_WED = datetime.date(2026, 7, 29)
NEXT_THU = datetime.date(2026, 7, 30)
PAST_WED = datetime.date(2026, 7, 15)

NOW = timezone.make_aware(datetime.datetime(2026, 7, 22, 7, 0))  # 마감 전 아침
NOW_0759 = timezone.make_aware(datetime.datetime(2026, 7, 22, 7, 59))
NOW_0800 = timezone.make_aware(datetime.datetime(2026, 7, 22, 8, 0))
NOW_1854 = timezone.make_aware(datetime.datetime(2026, 7, 22, 18, 54))
NOW_1855 = timezone.make_aware(datetime.datetime(2026, 7, 22, 18, 55))


def freeze_now(at=NOW):
    """클리닉 서비스의 기준 시각 고정(서비스 모듈 경유 timezone.now 만 patch)."""
    return mock.patch("apps.clinic.booking.timezone.now", return_value=at)


def make_user(login_id, role, name="사용자"):
    return User.objects.create_user(login_id=login_id, password=PASSWORD, name=name, role=role)


def make_student(login_id, name):
    user = make_user(login_id, User.Role.STUDENT, name=name)
    return Student.objects.create(
        user=user, unique_id=f"uid-{login_id}",
        enrollment_status=Student.EnrollmentStatus.REGISTERED,
    )


class ClinicFixtureMixin:
    """시험 1 + 슬롯(수 정원2·목 정원1·비활성) + 대상/비대상/무판정/제한 학생."""

    @classmethod
    def setUpTestData(cls):
        cls.exam = Exam.objects.create(name="7월 모의고사", exam_date=PAST_WED)
        cls.slot_wed = ClinicSlot.objects.create(
            weekday=3, start_time=datetime.time(19, 0), end_time=datetime.time(20, 0),
        )
        cls.slot_thu = ClinicSlot.objects.create(
            weekday=4, start_time=datetime.time(19, 0), end_time=datetime.time(20, 0),
        )
        cls.slot_off = ClinicSlot.objects.create(
            weekday=5, start_time=datetime.time(19, 0), end_time=datetime.time(20, 0),
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
            meet_url="https://meet.google.com/abc-defg-hij",
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
        self.assertIsNone(row["meet_url"])  # 시작 5분 전까지 URL 미노출
        after = self.get_clinic(at=NOW_1855).json()["my_requests"][0]
        self.assertTrue(after["link_active"])
        self.assertEqual(after["meet_url"], "https://meet.google.com/abc-defg-hij")

    def test_pending_request_has_no_link(self):
        self.make_request_row(self.s_target, self.slot_wed, TODAY)
        self.login(self.s_target.user)
        row = self.get_clinic(at=NOW_1855).json()["my_requests"][0]
        self.assertEqual(row["status"], "대기")
        self.assertFalse(row["link_active"])
        self.assertIsNone(row["meet_url"])

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
    """POST /api/student/clinic/requests — 자격·정원·마감·노쇼·중복 강제."""

    def setUp(self):
        self.login(self.s_target.user)

    def test_create_booking(self):
        res = self.book(self.slot_wed, NEXT_WED)
        self.assertEqual(res.status_code, 201)
        req = ClinicRequest.objects.get(student=self.s_target)
        self.assertEqual(req.status, ClinicRequest.Status.PENDING)
        self.assertEqual(req.exam_id, self.exam.exam_id)
        self.assertEqual(req.slot_id, self.slot_wed.slot_id)
        self.assertEqual(req.requested_date, NEXT_WED)
        self.assertEqual(req.requested_time, datetime.time(19, 0))
        body = res.json()
        self.assertEqual(body["request"]["clinic_id"], req.clinic_id)
        self.assertEqual(body["request"]["status"], "대기")
        self.assertEqual(body["request"]["requested_date"], "2026-07-29")
        self.assertEqual(body["request"]["requested_time"], "19:00")
        # 재조회 불필요 계약 — 확정된 슬롯 요약(정원·잔여석은 싣지 않는다)
        self.assertEqual(
            body["slot"],
            {
                "slot_id": self.slot_wed.slot_id,
                "weekday": 3,
                "start_time": "19:00",
                "end_time": "20:00",
            },
        )

    def test_one_active_request_closes_the_time(self):
        # 정원 1 고정(0721 회의) — 다른 학생 활성 신청 1건이면 곧바로 마감
        self.make_request_row(self.s_target2, self.slot_wed, NEXT_WED)
        self.assertEqual(self.book(self.slot_wed, NEXT_WED).status_code, 400)
        # 같은 슬롯의 다른 날짜는 영향 없다
        self.assertEqual(self.book(self.slot_wed, TODAY).status_code, 201)

    def test_same_day_cutoff_boundary(self):
        res = self.book(self.slot_wed, TODAY, at=NOW_0759)  # 07:59 — 허용
        self.assertEqual(res.status_code, 201)
        ClinicRequest.objects.all().delete()
        res = self.book(self.slot_wed, TODAY, at=NOW_0800)  # 08:00 — 차단
        self.assertEqual(res.status_code, 400)
        self.assertFalse(ClinicRequest.objects.exists())

    def test_past_date_400(self):
        self.assertEqual(self.book(self.slot_wed, PAST_WED).status_code, 400)

    def test_weekday_mismatch_400(self):
        self.assertEqual(self.book(self.slot_wed, NEXT_THU).status_code, 400)

    def test_non_target_403(self):
        for student in (self.s_not, self.s_none):
            self.login(student.user)
            res = self.book(self.slot_wed, NEXT_WED)
            self.assertEqual(res.status_code, 403, student.unique_id)
        self.assertFalse(ClinicRequest.objects.exists())

    def test_banned_403(self):
        self.login(self.s_banned.user)
        self.assertEqual(self.book(self.slot_wed, NEXT_WED).status_code, 403)

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
        self.make_request_row(self.s_target, self.slot_wed, NEXT_WED)
        self.assertEqual(self.book(self.slot_thu, THU).status_code, 400)

    def test_cancelled_request_does_not_block_new_booking(self):
        self.make_request_row(
            self.s_target, self.slot_wed, NEXT_WED, status=ClinicRequest.Status.CANCELLED
        )
        self.assertEqual(self.book(self.slot_thu, THU).status_code, 201)

    def test_invalid_body_400(self):
        for body in (
            {},
            {"exam_id": self.exam.exam_id, "slot_id": self.slot_wed.slot_id},
            {"exam_id": self.exam.exam_id, "requested_date": "2026-07-29"},
            {"exam_id": "x", "slot_id": self.slot_wed.slot_id, "requested_date": "2026-07-29"},
            {
                "exam_id": self.exam.exam_id,
                "slot_id": self.slot_wed.slot_id,
                "requested_date": "07/29/2026",
            },
        ):
            self.assertEqual(self.post_booking(body).status_code, 400, body)

    def test_unknown_or_inactive_slot_404(self):
        self.assertEqual(self.book(self.slot_off, datetime.date(2026, 7, 24)).status_code, 404)
        res = self.post_booking(
            {
                "exam_id": self.exam.exam_id,
                "slot_id": 999999,
                "requested_date": NEXT_WED.isoformat(),
            }
        )
        self.assertEqual(res.status_code, 404)

    def test_unknown_exam_404(self):
        res = self.post_booking(
            {
                "exam_id": 999999,
                "slot_id": self.slot_wed.slot_id,
                "requested_date": NEXT_WED.isoformat(),
            }
        )
        self.assertEqual(res.status_code, 404)

    def test_role_gates(self):
        self.client.logout()
        self.assertEqual(self.book(self.slot_wed, NEXT_WED).status_code, 403)
        self.login(self.parent_user)
        self.assertEqual(self.book(self.slot_wed, NEXT_WED).status_code, 403)


class ClinicBookingChangeTests(ClinicFixtureMixin, TestCase):
    """PATCH /api/student/clinic/requests/{id} — 같은 규칙 재검증 + 본인 것만."""

    def setUp(self):
        self.login(self.s_target.user)
        self.req = self.make_request_row(self.s_target, self.slot_wed, NEXT_WED)

    def test_change_date(self):
        res = self.patch_booking(self.req.clinic_id, {"requested_date": "2026-08-05"})
        self.assertEqual(res.status_code, 200)
        self.req.refresh_from_db()
        self.assertEqual(self.req.requested_date, datetime.date(2026, 8, 5))
        self.assertEqual(self.req.status, ClinicRequest.Status.PENDING)
        self.assertEqual(self.req.updated_at, NOW)  # 시간수정 추적 스탬프
        self.assertEqual(res.json()["request"]["requested_date"], "2026-08-05")

    def test_change_slot_resets_approval(self):
        staff = make_user("cl-staff", User.Role.ASSISTANT, name="조교")
        self.req.status = ClinicRequest.Status.APPROVED
        self.req.assigned_staff = staff
        self.req.meet_url = "https://meet.google.com/xyz"
        self.req.save(update_fields=["status", "assigned_staff", "meet_url"])
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
        self.assertIsNone(self.req.meet_url)

    def test_change_same_day_after_cutoff_400(self):
        req = self.make_request_row(self.s_target2, self.slot_wed, TODAY)
        self.login(self.s_target2.user)
        # 7/29 은 setUp 의 s_target 신청이 잡고 있다(정원 1) — 빈 수요일로 옮긴다
        res = self.patch_booking(req.clinic_id, {"requested_date": "2026-08-05"}, at=NOW_0800)
        self.assertEqual(res.status_code, 400)  # 당일 클리닉은 8시 후 이동 불가
        res = self.patch_booking(req.clinic_id, {"requested_date": "2026-08-05"}, at=NOW_0759)
        self.assertEqual(res.status_code, 200)

    def test_change_onto_today_after_cutoff_400(self):
        res = self.patch_booking(
            self.req.clinic_id, {"requested_date": TODAY.isoformat()}, at=NOW_0800
        )
        self.assertEqual(res.status_code, 400)

    def test_change_to_full_slot_400(self):
        self.make_request_row(self.s_target2, self.slot_thu, THU)
        res = self.patch_booking(
            self.req.clinic_id,
            {"slot_id": self.slot_thu.slot_id, "requested_date": THU.isoformat()},
        )
        self.assertEqual(res.status_code, 400)

    def test_change_excludes_self_from_capacity(self):
        # 정원 1 슬롯 안에서 날짜만 옮기기 — 본인 신청이 정원을 막지 않는다
        req = self.make_request_row(self.s_target2, self.slot_thu, THU)
        self.login(self.s_target2.user)
        res = self.patch_booking(req.clinic_id, {"requested_date": NEXT_THU.isoformat()})
        self.assertEqual(res.status_code, 200)

    def test_change_weekday_mismatch_400(self):
        res = self.patch_booking(self.req.clinic_id, {"requested_date": NEXT_THU.isoformat()})
        self.assertEqual(res.status_code, 400)

    def test_change_others_request_404(self):
        other = self.make_request_row(self.s_target2, self.slot_thu, THU)
        res = self.patch_booking(other.clinic_id, {"requested_date": NEXT_THU.isoformat()})
        self.assertEqual(res.status_code, 404)

    def test_change_cancelled_request_400(self):
        self.req.status = ClinicRequest.Status.CANCELLED
        self.req.save(update_fields=["status"])
        res = self.patch_booking(self.req.clinic_id, {"requested_date": "2026-08-05"})
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
        res = self.patch_booking(req.clinic_id, {"requested_date": NEXT_THU.isoformat()})
        self.assertEqual(res.status_code, 403)


class ClinicBookingCancelTests(ClinicFixtureMixin, TestCase):
    """POST /api/student/clinic/requests/{id}/cancel — 취소는 노쇼가 아니다."""

    def setUp(self):
        self.login(self.s_target.user)
        self.req = self.make_request_row(self.s_target, self.slot_wed, NEXT_WED)

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

    def test_cancel_same_day_boundary(self):
        req = self.make_request_row(self.s_target2, self.slot_wed, TODAY)
        self.login(self.s_target2.user)
        self.assertEqual(self.cancel_booking(req.clinic_id, at=NOW_0800).status_code, 400)
        self.assertEqual(self.cancel_booking(req.clinic_id, at=NOW_0759).status_code, 200)

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
    """

    def setUp(self):
        self.exam = Exam.objects.create(name="경합시험", exam_date=datetime.date(2026, 7, 15))
        self.slot = ClinicSlot.objects.create(
            weekday=4, start_time=datetime.time(19, 0), end_time=datetime.time(20, 0),
        )
        self.other_slot = ClinicSlot.objects.create(
            weekday=4, start_time=datetime.time(20, 0), end_time=datetime.time(21, 0),
        )
        # 실제 now 기준 다음 주 목요일(모델 요일 4) — 당일 마감 규칙과 무관한 미래일
        today = timezone.localdate()
        self.target_date = today + datetime.timedelta(days=((3 - today.weekday()) % 7) + 7)

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

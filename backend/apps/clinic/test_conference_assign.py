"""배정이 화상 스페이스를 만드는 계약 — clinic_admin.assign (PRD 3.2.4, §4).

여기서 고정하는 것:
  ① 링크를 주지 않으면 **새 스페이스를 만든다**(관리자가 손으로 붙여넣던 자리)
  ② 이미 링크가 있으면 재배정해도 **새로 만들지 않는다**(클리닉 1건 = 스페이스 1개)
  ③ 만들지 못하면 **아무것도 바뀌지 않는다** — 반쯤 배정된 행을 남기지 않는다
"""
import datetime

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import Student, User
from apps.grades.models import Exam

from . import booking, clinic_admin, supervision
from .booking import ClinicError
from .conferencing import (
    Conference,
    ConferenceAdapter,
    PermanentConferenceError,
    TemporaryConferenceError,
)
from .models import ClinicEligibility, ClinicRequest, ClinicSlot

WED = datetime.date(2026, 7, 22)


class RecordingAdapter(ConferenceAdapter):
    """만든 횟수를 세는 스탠드인. 클래스 변수로 세는 이유는 `get_adapter` 가
    호출 때마다 새 인스턴스를 만들기 때문(conferencing 계약 — 캐시 금지)."""

    calls = 0
    raises = None
    scheduled = []
    cancelled = []
    schedule_raises = None

    def create_space(self):
        RecordingAdapter.calls += 1
        if RecordingAdapter.raises is not None:
            raise RecordingAdapter.raises
        return Conference(
            provider="google_meet",
            ref=f"spaces/S{RecordingAdapter.calls}",
            url=f"https://meet.google.com/s-{RecordingAdapter.calls}",
        )

    def fetch_supervision(self, ref, *, file_as=None, key=None):
        return None

    def schedule_supervision(self, url, *, key, title, starts_at, minutes):
        if RecordingAdapter.schedule_raises is not None:
            raise RecordingAdapter.schedule_raises
        RecordingAdapter.scheduled.append((key, title, url, starts_at, minutes))

    def cancel_supervision(self, key):
        RecordingAdapter.cancelled.append(key)


ADAPTER_PATH = "apps.clinic.test_conference_assign.RecordingAdapter"


class ConferenceAssignTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = User.objects.create_user(
            login_id="cf-ast", password="pw-Secret-77!", name="조교", role=User.Role.ASSISTANT
        )
        cls.student = Student.objects.create(matching_key="3_7777")
        cls.exam = Exam.objects.create(name="7월 모의고사", exam_date=WED)
        cls.slot = ClinicSlot.objects.create(
            weekday=3, start_time=datetime.time(19, 0), end_time=datetime.time(20, 0)
        )

    def setUp(self):
        RecordingAdapter.calls = 0
        RecordingAdapter.raises = None

    def make_request(self, **extra):
        extra.setdefault("requested_time", self.slot.start_time)
        return ClinicRequest.objects.create(
            student=self.student,
            exam=self.exam,
            slot=self.slot,
            requested_date=WED,
            **extra,
        )

    # ① 자동 생성 -----------------------------------------------------------

    @override_settings(CLINIC_CONFERENCE_BACKEND=ADAPTER_PATH)
    def test_assign_without_url_creates_a_space(self):
        request = self.make_request()
        clinic_admin.assign(request, self.staff)
        request.refresh_from_db()
        self.assertEqual(RecordingAdapter.calls, 1)
        self.assertEqual(request.conference_provider, "google_meet")
        self.assertEqual(request.conference_ref, "spaces/S1")
        self.assertEqual(request.conference_url, "https://meet.google.com/s-1")
        self.assertEqual(request.status, ClinicRequest.Status.APPROVED)

    @override_settings(CLINIC_CONFERENCE_BACKEND=ADAPTER_PATH)
    def test_two_clinics_get_two_spaces(self):
        # 링크 재사용 금지(§4) — 신청이 다르면 스페이스도 다르다
        first = self.make_request()
        second = self.make_request(requested_time=datetime.time(20, 0))
        clinic_admin.assign(first, self.staff)
        clinic_admin.assign(second, self.staff)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertNotEqual(first.conference_url, second.conference_url)


    @override_settings(CLINIC_CONFERENCE_BACKEND=ADAPTER_PATH)
    def test_reassign_keeps_the_same_space(self):
        # 클리닉 1건 = 스페이스 1개. 조교만 바뀌는데 링크가 갈리면 학생이
        # 이미 받은 링크가 죽는다.
        request = self.make_request()
        clinic_admin.assign(request, self.staff)
        first_url = request.conference_url
        other = User.objects.create_user(
            login_id="cf-adm", password="pw-Secret-77!", name="관리자", role=User.Role.ADMIN
        )
        clinic_admin.assign(request, other)
        request.refresh_from_db()
        self.assertEqual(RecordingAdapter.calls, 1)
        self.assertEqual(request.conference_url, first_url)
        self.assertEqual(request.assigned_staff_id, other.user_id)

    # ④ 실패 ----------------------------------------------------------------

    @override_settings(CLINIC_CONFERENCE_BACKEND="")
    def test_unconfigured_provider_blocks_assign(self):
        request = self.make_request()
        with self.assertRaises(ClinicError):
            clinic_admin.assign(request, self.staff)

    @override_settings(CLINIC_CONFERENCE_BACKEND="")
    def test_failure_leaves_the_request_untouched(self):
        # 반쯤 배정된 행(승인배정인데 링크 없음)은 학생에게 빈 안내가 된다
        request = self.make_request()
        with self.assertRaises(ClinicError):
            clinic_admin.assign(request, self.staff)
        request.refresh_from_db()
        self.assertEqual(request.status, ClinicRequest.Status.PENDING)
        self.assertIsNone(request.assigned_staff)
        self.assertIsNone(request.conference_url)

    @override_settings(CLINIC_CONFERENCE_BACKEND=ADAPTER_PATH)
    def test_temporary_failure_asks_to_retry(self):
        RecordingAdapter.raises = TemporaryConferenceError("구글에 닿지 못했습니다")
        request = self.make_request()
        with self.assertRaises(ClinicError) as caught:
            clinic_admin.assign(request, self.staff)
        self.assertEqual(caught.exception.http_status, 503)

    @override_settings(CLINIC_CONFERENCE_BACKEND=ADAPTER_PATH)
    def test_permanent_failure_is_a_bad_request(self):
        RecordingAdapter.raises = PermanentConferenceError("자격증명이 없습니다")
        request = self.make_request()
        with self.assertRaises(ClinicError) as caught:
            clinic_admin.assign(request, self.staff)
        self.assertEqual(caught.exception.http_status, 400)

    @override_settings(CLINIC_CONFERENCE_BACKEND=ADAPTER_PATH)
    def test_provider_failure_message_reaches_the_admin(self):
        # 사유가 안 보이면 관리자는 무엇을 고쳐야 할지 알 수 없다
        RecordingAdapter.raises = PermanentConferenceError("구글 미트 자격증명이 없습니다")
        request = self.make_request()
        with self.assertRaises(ClinicError) as caught:
            clinic_admin.assign(request, self.staff)
        self.assertIn("자격증명", caught.exception.message)


class SupervisionScheduleTests(TestCase):
    """배정하면 감독이 **미리 걸린다** — 시작 시각은 업체가 지킨다."""

    @classmethod
    def setUpTestData(cls):
        cls.staff = User.objects.create_user(
            login_id="sch-ast", password="pw-Secret-77!", name="조교", role=User.Role.ASSISTANT
        )
        cls.student_user = User.objects.create_user(
            login_id="sch-stu", password="pw-Secret-77!", name="김하늘", role=User.Role.STUDENT
        )
        cls.student = Student.objects.create(user=cls.student_user, matching_key="김하늘0001")
        # 창구(시험일+6일) 안에 들어오도록 시험일을 오늘로 둔다
        today = timezone.localdate()
        cls.exam = Exam.objects.create(name="7월 모의고사", exam_date=today)
        cls.date = today + datetime.timedelta(days=1)
        weekday = (cls.date.weekday() + 1) % 7  # 모델 규약: 0=일…6=토
        cls.slot = ClinicSlot.objects.create(
            weekday=weekday, start_time=datetime.time(19, 0), end_time=datetime.time(20, 0)
        )
        # 시간 변경은 **같은 날 다른 시간**이다 — 창구가 6일뿐이라 같은 요일의
        # 다른 날짜로는 옮길 수 없다.
        cls.other_slot = ClinicSlot.objects.create(
            weekday=weekday, start_time=datetime.time(20, 0), end_time=datetime.time(21, 0)
        )
        # 시간 변경은 자격 게이트를 지난다 — 대상자로 세워 둔다
        ClinicEligibility.objects.create(exam=cls.exam, student=cls.student, is_target=True)

    def setUp(self):
        RecordingAdapter.scheduled = []
        RecordingAdapter.cancelled = []

    def make_request(self, **extra):
        extra.setdefault("status", ClinicRequest.Status.PENDING)
        return ClinicRequest.objects.create(
            student=self.student,
            exam=self.exam,
            slot=self.slot,
            requested_date=self.date,
            requested_time=datetime.time(19, 0),
            **extra,
        )

    @override_settings(CLINIC_CONFERENCE_BACKEND=ADAPTER_PATH)
    def test_assigning_books_the_bot(self):
        request = self.make_request()
        clinic_admin.assign(request, self.staff)
        (key, title, url, starts_at, minutes), = RecordingAdapter.scheduled
        # 클리닉마다 하나이고 바뀌지 않는 이름 — 시간이 바뀌면 덮어쓴다
        self.assertEqual(key, f"clinic{request.clinic_id}")
        # 일정 제목 = 나중에 전사를 되찾을 제목
        self.assertEqual(title, supervision.artifact_path(request))
        self.assertEqual(url, request.conference_url)
        self.assertEqual(starts_at, supervision.starts_at(request))
        self.assertEqual(minutes, 60)

    @override_settings(CLINIC_CONFERENCE_BACKEND=ADAPTER_PATH)
    def test_cancelling_takes_the_bot_off(self):
        # 안 거두면 **아무도 없는 방에 봇이 들어가** 빈 기록을 남긴다.
        request = self.make_request()
        clinic_admin.assign(request, self.staff)
        booking.cancel_booking(request)
        self.assertEqual(RecordingAdapter.cancelled, [f"clinic{request.clinic_id}"])

    @override_settings(CLINIC_CONFERENCE_BACKEND=ADAPTER_PATH)
    def test_moving_the_time_takes_the_old_booking_off(self):
        # 옮긴 뒤 다시 배정하면 새로 걸린다. 옛 예약이 남아 있으면 봇이 두 번 간다.
        request = self.make_request()
        clinic_admin.assign(request, self.staff)
        booking.change_booking(request, self.other_slot, self.date)
        self.assertEqual(RecordingAdapter.cancelled, [f"clinic{request.clinic_id}"])

    @override_settings(CLINIC_CONFERENCE_BACKEND=ADAPTER_PATH)
    def test_a_booking_failure_does_not_undo_the_assignment(self):
        # 예약이 실패했다고 배정을 무르면 조교·링크가 통째로 날아간다.
        # 감독은 다음에 다시 걸 수 있지만 배정은 사람이 다시 해야 한다.
        RecordingAdapter.schedule_raises = TemporaryConferenceError("업체 장애")
        self.addCleanup(setattr, RecordingAdapter, "schedule_raises", None)
        request = self.make_request()
        clinic_admin.assign(request, self.staff)
        request.refresh_from_db()
        self.assertEqual(request.status, ClinicRequest.Status.APPROVED)
        self.assertTrue(request.conference_url)

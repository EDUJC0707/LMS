"""감독 자료 수집 — 끝난 클리닉에서 요약·문서 링크를 가져와 평가에 붙인다.

여기서 고정하는 것:
  ① 대상 고르기: 끝난 지 30분 넘은 `승인배정` 건만, 30일 안쪽만
  ② **두 번 돌려도 같다** — 이미 가져온 건 건드리지 않는다(어떤 주기로 돌려도
     되게 만드는 유일한 성질이다. 30분마다 + 정오에 한 번 = 같은 명령 두 번)
  ③ 회의가 없었으면(아무도 안 들어옴 / 조교가 아이패드로 호스트) 조용히 넘어간다
  ④ 저장소 정리 이름은 폴더·날짜가 영문/숫자, 이름만 한글
"""
import datetime

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import Student, User
from apps.grades.models import Exam

from . import clinic_admin, supervision
from .conferencing import (
    Conference,
    ConferenceAdapter,
    Supervision,
    TemporaryConferenceError,
)
from .models import ClinicEvaluation, ClinicRequest, ClinicSlot

WED = datetime.date(2026, 7, 22)


class StubAdapter(ConferenceAdapter):
    """미리 정해둔 감독 자료를 돌려준다. 요청받은 정리 경로를 기록해 둔다."""

    result = None
    filed_as = []
    asked = []
    started = []
    titles = []
    start_raises = None

    def create_space(self):
        return Conference(provider="google_meet", ref="spaces/S", url="https://x/s")

    def fetch_supervision(self, ref, *, file_as=None, key=None):
        StubAdapter.asked.append(ref)
        StubAdapter.filed_as.append(file_as)
        return StubAdapter.result

    def start_supervision(self, url, *, title, minutes):
        if StubAdapter.start_raises:
            raise StubAdapter.start_raises
        StubAdapter.started.append((url, minutes))
        StubAdapter.titles.append(title)


ADAPTER = "apps.clinic.test_supervision.StubAdapter"


@override_settings(CLINIC_CONFERENCE_BACKEND=ADAPTER)
class CollectSupervisionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = User.objects.create_user(
            login_id="sv-ast", password="pw-Secret-77!", name="조교", role=User.Role.ASSISTANT
        )
        cls.student_user = User.objects.create_user(
            login_id="sv-stu", password="pw-Secret-77!", name="김하늘", role=User.Role.STUDENT
        )
        cls.student = Student.objects.create(user=cls.student_user, matching_key="김하늘0001")
        cls.exam = Exam.objects.create(name="7월 모의고사", exam_date=WED)
        cls.slot = ClinicSlot.objects.create(
            weekday=3, start_time=datetime.time(19, 0), end_time=datetime.time(20, 0)
        )

    def setUp(self):
        StubAdapter.asked = []
        StubAdapter.filed_as = []
        StubAdapter.result = Supervision(
            transcript_ref="1SPPdoc",
            transcript_url="https://docs.google.com/document/d/1SPPdoc/edit",
            summary="요약\n오답 원인 설명 충실.",
        )

    def make_request(self, days_ago=1, **extra):
        extra.setdefault("status", ClinicRequest.Status.APPROVED)
        extra.setdefault("conference_provider", "google_meet")
        extra.setdefault("conference_ref", "spaces/S1")
        extra.setdefault("conference_url", "https://meet.google.com/a-b-c")
        return ClinicRequest.objects.create(
            student=self.student,
            exam=self.exam,
            slot=self.slot,
            assigned_staff=self.staff,
            requested_date=timezone.localdate() - datetime.timedelta(days=days_ago),
            requested_time=datetime.time(19, 0),
            **extra,
        )

    # ① 대상 고르기 --------------------------------------------------------

    def test_collects_a_finished_clinic(self):
        request = self.make_request()
        supervision.collect()
        evaluation = ClinicEvaluation.objects.get(clinic=request)
        self.assertEqual(evaluation.transcript_ref, "1SPPdoc")
        self.assertEqual(
            evaluation.transcript_url, "https://docs.google.com/document/d/1SPPdoc/edit"
        )
        self.assertIn("오답 원인", evaluation.ai_summary)

    def test_skips_clinics_without_a_space(self):
        # 관리자가 링크를 직접 넣은 건 — 우리가 만든 스페이스가 아니라 가져올 게 없다
        self.make_request(conference_provider=None, conference_ref=None)
        supervision.collect()
        self.assertEqual(StubAdapter.asked, [])

    def test_skips_clinics_that_were_not_assigned(self):
        self.make_request(status=ClinicRequest.Status.CANCELLED)
        supervision.collect()
        self.assertEqual(StubAdapter.asked, [])

    def test_skips_clinics_older_than_the_record_window(self):
        # 회의 기록이 30일 뒤 사라진다 — 그 뒤로는 물어볼 곳이 없다
        self.make_request(days_ago=31)
        supervision.collect()
        self.assertEqual(StubAdapter.asked, [])

    def test_skips_clinics_that_have_not_happened_yet(self):
        self.make_request(days_ago=-1)
        supervision.collect()
        self.assertEqual(StubAdapter.asked, [])

    # ② 몇 번을 돌려도 같다 -------------------------------------------------

    def test_running_twice_collects_once(self):
        self.make_request()
        supervision.collect()
        supervision.collect()
        self.assertEqual(len(StubAdapter.asked), 1)

    def test_leaves_an_existing_evaluation_alone(self):
        # 관리자가 이미 평가를 적어 둔 건에도 요약만 얹고 판정은 안 건드린다
        request = self.make_request()
        ClinicEvaluation.objects.create(
            clinic=request, overall_result=ClinicEvaluation.OverallResult.QUALIFIED
        )
        supervision.collect()
        evaluation = ClinicEvaluation.objects.get(clinic=request)
        self.assertEqual(evaluation.overall_result, ClinicEvaluation.OverallResult.QUALIFIED)
        self.assertEqual(evaluation.transcript_ref, "1SPPdoc")

    # ③ 회의가 없었던 경우 --------------------------------------------------

    def test_no_meeting_leaves_the_row_empty(self):
        # 아무도 안 들어왔거나 조교가 아이패드로 호스트해서 전사가 아예 없다.
        # 실패가 아니다 — 다음 번에 다시 물어볼 수 있게 그냥 비워 둔다.
        request = self.make_request()
        StubAdapter.result = None
        supervision.collect()
        self.assertFalse(ClinicEvaluation.objects.filter(clinic=request).exists())

    def test_summaryless_artifact_still_stores_the_link(self):
        # 자를 자리를 못 찾아 요약이 비어도 문서 링크는 남긴다 — 사람이 열어 보면 된다
        request = self.make_request()
        StubAdapter.result = Supervision(
            transcript_ref="1SPPdoc", transcript_url="https://x/doc", summary=None
        )
        supervision.collect()
        evaluation = ClinicEvaluation.objects.get(clinic=request)
        self.assertIsNone(evaluation.ai_summary)
        self.assertEqual(evaluation.transcript_url, "https://x/doc")

    # ④ 정리 이름 ----------------------------------------------------------

    def test_filing_path_is_dated_and_named(self):
        request = self.make_request(days_ago=1)
        supervision.collect()
        date = request.requested_date
        self.assertEqual(
            StubAdapter.filed_as[0],
            f"clinic/{date:%Y-%m}/{date:%Y-%m-%d}_1900_김하늘0001",
        )

    def test_filing_path_works_without_a_student_account(self):
        # 예비등록이라 User 가 아직 없어도 원번은 있다 — 경로가 성립해야 한다
        # (원번이 곧 `{이름}{뒷4}` 라 이름을 따로 붙일 일도 없다)
        accountless = Student.objects.create(matching_key="박지우0002")
        request = self.make_request()
        request.student = accountless
        request.save(update_fields=["student"])
        supervision.collect()
        self.assertTrue(StubAdapter.filed_as[0].endswith("_1900_박지우0002"))


class QueueSupervisionTests(CollectSupervisionTests):
    """대기열 행이 수집한 감독 자료를 실어 내리는가 — 화면이 읽을 자리."""

    def test_row_carries_the_collected_summary(self):
        from . import clinic_admin

        request = self.make_request()
        supervision.collect()
        row = clinic_admin.queue_row(ClinicRequest.objects.get(pk=request.pk))
        self.assertEqual(row["supervision"]["summary"], "요약\n오답 원인 설명 충실.")
        self.assertEqual(
            row["supervision"]["transcript_url"],
            "https://docs.google.com/document/d/1SPPdoc/edit",
        )

    def test_row_without_a_meeting_says_so(self):
        # 조교가 아이패드로 호스트했거나 아무도 안 들어온 회차 — 빈 칸이 아니라
        # "없다"가 드러나야 평가 안 한 것처럼 보이지 않는다
        from . import clinic_admin

        request = self.make_request()
        row = clinic_admin.queue_row(request)
        self.assertIsNone(row["supervision"])

    def test_past_filter_excludes_upcoming(self):
        past = self.make_request(days_ago=3)
        self.make_request(days_ago=-3)
        rows = clinic_admin.queue_rows(period="지난")
        self.assertEqual([r["clinic_id"] for r in rows], [past.clinic_id])

    def test_upcoming_filter_excludes_past(self):
        self.make_request(days_ago=3)
        upcoming = self.make_request(days_ago=-3)
        rows = clinic_admin.queue_rows(period="예정")
        self.assertEqual([r["clinic_id"] for r in rows], [upcoming.clinic_id])


class CollectionWindowTests(CollectSupervisionTests):
    """시각까지 본다 — 날짜만 보면 저녁 수업이 다음 날 새벽까지 안 잡힌다."""

    def at(self, **delta):
        start = timezone.make_aware(datetime.datetime(2026, 8, 12, 19, 0))
        return start + datetime.timedelta(**delta)

    def evening_clinic(self):
        request = self.make_request(days_ago=0)
        request.requested_date = datetime.date(2026, 8, 12)
        request.requested_time = datetime.time(19, 0)
        request.save(update_fields=["requested_date", "requested_time"])
        return request

    def test_collected_thirty_minutes_after_it_started(self):
        # 19:00 수업이면 19:30 에 잡혀야 한다 — 다음 날이 아니라
        request = self.evening_clinic()
        supervision.collect(now=self.at(minutes=31))
        self.assertEqual(StubAdapter.asked, [request.conference_ref])

    def test_not_collected_while_it_is_still_running(self):
        self.evening_clinic()
        supervision.collect(now=self.at(minutes=10))
        self.assertEqual(StubAdapter.asked, [])


@override_settings(CLINIC_CONFERENCE_BACKEND=ADAPTER)
class DispatchSupervisionTests(TestCase):
    """봇 투입 — 시작한 클리닉에 **한 번만** 넣는다.

    Fireflies 는 예약 참가가 없어서(진행 중인 회의에만 넣을 수 있다) 시작 시각
    근처에 누군가 불러 줘야 한다. 그 "누군가"가 여기다.
    """

    @classmethod
    def setUpTestData(cls):
        cls.staff = User.objects.create_user(
            login_id="dp-ast", password="pw-Secret-77!", name="조교", role=User.Role.ASSISTANT
        )
        cls.student_user = User.objects.create_user(
            login_id="dp-stu", password="pw-Secret-77!", name="김하늘", role=User.Role.STUDENT
        )
        cls.student = Student.objects.create(user=cls.student_user, matching_key="김하늘0001")
        cls.exam = Exam.objects.create(name="7월 모의고사", exam_date=WED)
        cls.slot = ClinicSlot.objects.create(
            weekday=3, start_time=datetime.time(19, 0), end_time=datetime.time(20, 0)
        )

    def setUp(self):
        StubAdapter.started = []
        StubAdapter.titles = []

    def make_request(self, **extra):
        extra.setdefault("status", ClinicRequest.Status.APPROVED)
        extra.setdefault("conference_provider", "google_meet")
        extra.setdefault("conference_ref", "spaces/S1")
        extra.setdefault("conference_url", "https://meet.google.com/a-b-c")
        return ClinicRequest.objects.create(
            student=self.student,
            exam=self.exam,
            slot=self.slot,
            assigned_staff=self.staff,
            requested_date=timezone.localdate(),
            requested_time=datetime.time(19, 0),
            **extra,
        )

    def at(self, hour, minute):
        return supervision.starts_at(
            ClinicRequest(requested_date=timezone.localdate(), requested_time=datetime.time(0, 0))
        ) + datetime.timedelta(hours=hour, minutes=minute)

    def test_starts_supervision_for_a_clinic_that_just_began(self):
        request = self.make_request()
        supervision.dispatch(now=self.at(19, 0))
        self.assertEqual(StubAdapter.started, [("https://meet.google.com/a-b-c", 60)])
        request.refresh_from_db()
        self.assertIsNotNone(request.supervision_started_at)

    def test_files_it_under_the_same_name_collection_will_look_for(self):
        request = self.make_request()
        supervision.dispatch(now=self.at(19, 0))
        self.assertEqual(StubAdapter.titles, [supervision.artifact_path(request)])

    def test_does_not_send_a_second_bot(self):
        self.make_request()
        supervision.dispatch(now=self.at(19, 0))
        supervision.dispatch(now=self.at(19, 1))
        self.assertEqual(len(StubAdapter.started), 1)

    def test_ignores_a_clinic_that_has_not_started(self):
        self.make_request()
        supervision.dispatch(now=self.at(18, 59))
        self.assertEqual(StubAdapter.started, [])

    def test_ignores_a_clinic_that_started_too_long_ago(self):
        # 워커가 한참 죽어 있었다 — 이미 끝난 회의에 봇을 넣으면 돈만 나간다
        self.make_request()
        supervision.dispatch(now=self.at(19, 0) + supervision.DISPATCH_WINDOW)
        self.assertEqual(StubAdapter.started, [])

    def test_skips_clinics_without_a_space(self):
        self.make_request(conference_provider=None, conference_ref=None, conference_url=None)
        supervision.dispatch(now=self.at(19, 0))
        self.assertEqual(StubAdapter.started, [])

    def test_a_failure_leaves_it_to_be_retried(self):
        StubAdapter.start_raises = TemporaryConferenceError("업체 장애")
        self.addCleanup(setattr, StubAdapter, "start_raises", None)
        request = self.make_request()
        counts = supervision.dispatch(now=self.at(19, 0))
        self.assertEqual(counts["failed"], 1)
        request.refresh_from_db()
        self.assertIsNone(request.supervision_started_at)

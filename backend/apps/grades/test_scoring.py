"""성적 집계 계약 — 미제출 표기 · 백분위 · 석차 (apps/grades/scoring.py).

`is_taken` 이 "시험 봤나"의 단일 원천이라는 계약을 여기서 고정한다. 예전에는
`attendances.exam_taken` 과 두 곳에 갈려 있었고, **운영에서는 미제출 성적 행을
아무도 안 만들어서** 답안지를 안 낸 학생이 성적 화면에 아예 없었다.
"""
import datetime
from decimal import Decimal

from django.test import TestCase

from apps.accounts.models import User
from apps.clinic.models import ClinicEligibility
from apps.curriculum.models import Class, Course, CourseEnrollment, CourseWeek

from . import scoring
from .models import AnswerSheet, Attendance, ClassSession, Exam, Score
from .test_grade_report_api import make_student


class MarkMissingTests(TestCase):
    """답안지가 안 들어온 학생 = 시험 미제출. 담임 입력이 아니라 판독이 정한다."""

    @classmethod
    def setUpTestData(cls):
        cls.exam = Exam.objects.create(name="8월 미니", exam_date=datetime.date(2026, 8, 12))
        course = Course.objects.create(name="고2 화학", target_grade=2)
        week = CourseWeek.objects.create(course=course, week_no=1)
        cls.session = ClassSession.objects.create(
            session_date=datetime.date(2026, 8, 12), course_week=week, exam=cls.exam
        )
        cls.submitted = make_student("stu-sub", "김서연")
        cls.absentee = make_student("stu-miss", "이민준")
        for student in (cls.submitted, cls.absentee):
            Attendance.objects.create(
                session=cls.session, student=student, status=Attendance.Status.PRESENT
            )
        AnswerSheet.objects.create(
            exam=cls.exam, student=cls.submitted, scan_image_path="omr/a.jpg",
            match_status=AnswerSheet.MatchStatus.MATCHED,
        )
        Score.objects.create(
            exam=cls.exam, student=cls.submitted, total_score=Decimal("80"), is_taken=True
        )

    def test_a_student_without_a_sheet_gets_a_not_taken_score(self):
        created = scoring.mark_missing(self.exam)

        self.assertEqual(created, 1)
        row = Score.objects.get(exam=self.exam, student=self.absentee)
        self.assertFalse(row.is_taken)
        self.assertIsNone(row.total_score)

    def test_it_does_not_touch_a_student_who_submitted(self):
        scoring.mark_missing(self.exam)

        row = Score.objects.get(exam=self.exam, student=self.submitted)
        self.assertTrue(row.is_taken)
        self.assertEqual(float(row.total_score), 80.0)

    def test_running_twice_does_not_duplicate(self):
        scoring.mark_missing(self.exam)
        scoring.mark_missing(self.exam)

        self.assertEqual(Score.objects.filter(exam=self.exam).count(), 2)

    def test_without_a_session_it_invents_nothing(self):
        """회차가 안 매여 있으면 "봤어야 할 사람"을 알 수 없다."""
        lonely = Exam.objects.create(name="회차 미매핑", exam_date=datetime.date(2026, 8, 12))

        self.assertEqual(scoring.mark_missing(lonely), 0)
        self.assertEqual(Score.objects.filter(exam=lonely).count(), 0)


class MarkPresentTests(TestCase):
    """대조된 장이 곧 출석이다 — 조교가 같은 명단을 두 번 찍지 않게 (FLOW 3-2·3-4)."""

    @classmethod
    def setUpTestData(cls):
        cls.exam = Exam.objects.create(name="3주차 미니", exam_date=datetime.date(2026, 9, 18))
        course = Course.objects.create(name="2026 여름 N제", total_weeks=3)
        cls.klass = Class.objects.create(
            course=course, name="목 6.5 대치러셀", start_date=datetime.date(2026, 9, 4)
        )
        week = CourseWeek.objects.create(course=course, week_no=3)
        cls.session = ClassSession.objects.create(
            session_date=datetime.date(2026, 9, 18),
            course_week=week,
            klass=cls.klass,
            week_no=3,
            exam=cls.exam,
        )
        cls.taker = make_student("stu-present", "김하늘")
        cls.skipper = make_student("stu-noshow", "이서준")
        for student in (cls.taker, cls.skipper):
            CourseEnrollment.objects.create(
                student=student, course=course, klass=cls.klass
            )
        AnswerSheet.objects.create(
            exam=cls.exam, student=cls.taker, scan_image_path="omr/present.png",
            match_status=AnswerSheet.MatchStatus.MATCHED,
        )

    def test_a_matched_sheet_marks_the_student_present(self):
        self.assertEqual(scoring.mark_present(self.exam), 1)

        row = Attendance.objects.get(session=self.session, student=self.taker)
        self.assertEqual(row.status, Attendance.Status.PRESENT)
        # 사람이 안 찍었다는 표시 — 다음 판독이 덮어도 되는 자리다.
        self.assertIsNone(row.marked_by_id)

    def test_an_unmatched_student_is_left_alone(self):
        """대조 안 된 학생은 `미입력` 이다 — 결석으로 찍으면 결석 문자가 나간다."""
        scoring.mark_present(self.exam)

        self.assertFalse(Attendance.objects.filter(student=self.skipper).exists())

    def test_running_twice_changes_nothing(self):
        scoring.mark_present(self.exam)

        self.assertEqual(scoring.mark_present(self.exam), 0)
        self.assertEqual(Attendance.objects.filter(session=self.session).count(), 1)

    def test_it_does_not_overwrite_what_a_person_marked(self):
        """조교가 손으로 고친 값은 재판독이 되돌리지 못한다(FLOW 3-2)."""
        actor = User.objects.create_user(
            login_id="staff-omr", password="pw1234!!", role=User.Role.ADMIN, name="조교"
        )
        Attendance.objects.create(
            session=self.session, student=self.taker,
            status=Attendance.Status.ABSENT, marked_by=actor,
        )

        self.assertEqual(scoring.mark_present(self.exam), 0)
        row = Attendance.objects.get(session=self.session, student=self.taker)
        self.assertEqual(row.status, Attendance.Status.ABSENT)

    def test_it_does_not_undo_a_cleared_entry(self):
        """눌렀던 것을 해제한 `미입력` 도 사람의 판단이다 — 다시 찍지 않는다."""
        actor = User.objects.create_user(
            login_id="staff-clear", password="pw1234!!", role=User.Role.ADMIN, name="조교"
        )
        Attendance.objects.create(
            session=self.session, student=self.taker,
            status=Attendance.Status.UNENTERED, marked_by=actor,
        )

        self.assertEqual(scoring.mark_present(self.exam), 0)

    def test_the_missing_list_comes_from_the_class_roster(self):
        """출결 행이 없어도 반 명단에 있으면 미제출이다 — 지금까지 0건이었다."""
        scoring.mark_present(self.exam)

        self.assertEqual(scoring.mark_missing(self.exam), 1)
        self.assertFalse(Score.objects.get(exam=self.exam, student=self.skipper).is_taken)


class RankTests(TestCase):
    """백분위 = (미만 + 동점/2) / 응시 × 100. 동점은 반씩 나눈다."""

    @classmethod
    def setUpTestData(cls):
        cls.exam = Exam.objects.create(name="8월 순위", exam_date=datetime.date(2026, 8, 12))
        cls.students = {}
        # {A 60, B 80, C 80, D 60} — 동점이 둘씩
        for tag, total in (("a", 60), ("b", 80), ("c", 80), ("d", 60)):
            student = make_student(f"stu-rank-{tag}", f"학생{tag}")
            cls.students[tag] = student
            Score.objects.create(
                exam=cls.exam, student=student, total_score=Decimal(total), is_taken=True
            )

    def scores(self):
        scoring.rank(self.exam)
        return {
            tag: Score.objects.get(exam=self.exam, student=student)
            for tag, student in self.students.items()
        }

    def test_tied_students_get_the_same_percentile(self):
        rows = self.scores()

        # A: 미만 0 + 동점 2/2 = 1 → 1/4 = 25.0
        self.assertEqual(float(rows["a"].percentile), 25.0)
        self.assertEqual(float(rows["d"].percentile), 25.0)
        # B: 미만 2 + 동점 2/2 = 3 → 3/4 = 75.0
        self.assertEqual(float(rows["b"].percentile), 75.0)
        self.assertEqual(float(rows["c"].percentile), 75.0)

    def test_tied_students_share_the_rank(self):
        rows = self.scores()

        # 80점 둘은 공동 1등 → 1/4 = 25%, 60점 둘은 공동 3등 → 3/4 = 75%
        self.assertEqual(float(rows["b"].rank_top_pct), 25.0)
        self.assertEqual(float(rows["c"].rank_top_pct), 25.0)
        self.assertEqual(float(rows["a"].rank_top_pct), 75.0)

    def test_a_missing_student_has_no_rank(self):
        """미응시는 순위가 없다 — 남겨 두면 지난 값이 그대로 보인다."""
        skipped = make_student("stu-rank-x", "미제출")
        Score.objects.create(
            exam=self.exam, student=skipped, is_taken=False,
            percentile=Decimal("99"), rank_top_pct=Decimal("1"),
        )

        scoring.rank(self.exam)

        row = Score.objects.get(exam=self.exam, student=skipped)
        self.assertIsNone(row.percentile)
        self.assertIsNone(row.rank_top_pct)

    def test_rank_follows_a_changed_score(self):
        """한 명의 점수가 바뀌면 전원의 백분위가 흔들린다."""
        self.scores()
        Score.objects.filter(exam=self.exam, student=self.students["a"]).update(
            total_score=Decimal("100")
        )

        rows = self.scores()

        self.assertEqual(float(rows["a"].percentile), 87.5)  # 미만 3 + 동점 1/2 = 3.5/4
        self.assertEqual(float(rows["a"].rank_top_pct), 25.0)


class AnonymousScoreTests(TestCase):
    """누군지는 안 알리고 점수만 준 학생 — 평균에는 들고 학생에는 안 붙는다.

    자기보고 지면(성적 조사 카드)이라 성명·번호를 비운 채 점수만 적어 내는 장이
    실제로 온다. 그 점수를 버리면 평균이 그 학생들 없이 나간다.
    """

    @classmethod
    def setUpTestData(cls):
        cls.exam = Exam.objects.create(
            name="6월 모의평가", exam_date=datetime.date(2026, 6, 12), kind=Exam.Kind.MOCK
        )
        cls.student = make_student("stu-anon", "김서연")
        Score.objects.create(
            exam=cls.exam, student=cls.student, total_score=Decimal("40"), is_taken=True
        )

    def anonymous_sheet(self, score, confirmed):
        return AnswerSheet.objects.create(
            exam=self.exam,
            student=None,
            scan_image_path=f"omr/scans/{self.exam.pk}/{score}.jpg",
            match_status=AnswerSheet.MatchStatus.INVALID,
            recognized_score=score,
            is_corrected=confirmed,
        )

    def test_a_confirmed_anonymous_sheet_joins_the_population(self):
        self.anonymous_sheet(50, confirmed=True)

        self.assertEqual(scoring.anonymous_totals(self.exam), [50])

    def test_an_unconfirmed_one_does_not(self):
        """조교가 아직 안 본 장은 주인이 나올 수 있다 — 세면 평균이 나중에 바뀐다."""
        self.anonymous_sheet(50, confirmed=False)

        self.assertEqual(scoring.anonymous_totals(self.exam), [])

    def test_it_pushes_a_student_percentile_down(self):
        """익명 장을 빼면 남은 학생 백분위가 실제보다 높게 나온다."""
        scoring.rank(self.exam)
        alone = Score.objects.get(exam=self.exam, student=self.student).percentile

        self.anonymous_sheet(50, confirmed=True)
        scoring.rank(self.exam)

        joined = Score.objects.get(exam=self.exam, student=self.student).percentile
        self.assertEqual(float(alone), 50.0)  # 혼자면 (0 + 1/2)/1
        self.assertEqual(float(joined), 25.0)  # 50점이 위에 있다 → (0 + 1/2)/2
        self.assertLess(joined, alone)

    def test_it_never_becomes_a_score_row(self):
        """붙일 학생이 없다 — scores.student 는 NOT NULL 이고 그게 맞다."""
        self.anonymous_sheet(50, confirmed=True)
        scoring.finalize_exam(self.exam)

        self.assertEqual(Score.objects.filter(exam=self.exam).count(), 1)


class ClinicTargetTests(TestCase):
    """클리닉 대상 판정 — 출석 + 응시 + 평균 미달 (FLOW 3-7).

    이 판정을 만드는 코드가 시드밖에 없었다. 신청 화면은 판정 없는 학생을 403 으로
    막으므로(`clinic.booking._ensure_can_book`) 실서비스에서는 아무도 클리닉을
    잡을 수 없었고, 첫 수업에서 시험을 보니 오픈 첫 주에 걸린다.
    """

    @classmethod
    def setUpTestData(cls):
        cls.exam = Exam.objects.create(name="1주차 미니", exam_date=datetime.date(2026, 9, 4))
        course = Course.objects.create(name="2026 여름 N제", total_weeks=1)
        klass = Class.objects.create(course=course, name="목 6.5 대치러셀")
        week = CourseWeek.objects.create(course=course, week_no=1)
        cls.session = ClassSession.objects.create(
            session_date=datetime.date(2026, 9, 4),
            course_week=week,
            klass=klass,
            week_no=1,
            exam=cls.exam,
        )
        # 평균 60 — 아래 40, 위 80, 그리고 결석·미응시 하나씩
        cls.low = make_student("stu-low", "김하늘")
        cls.high = make_student("stu-high", "이서준")
        cls.absent = make_student("stu-away", "박지우")
        cls.skipped = make_student("stu-skip", "최유진")
        for student in (cls.low, cls.high, cls.absent, cls.skipped):
            CourseEnrollment.objects.create(student=student, course=course, klass=klass)
        for student, status in (
            (cls.low, Attendance.Status.PRESENT),
            (cls.high, Attendance.Status.PRESENT),
            (cls.absent, Attendance.Status.ABSENT),
            (cls.skipped, Attendance.Status.PRESENT),
        ):
            Attendance.objects.create(session=cls.session, student=student, status=status)
        for student, total in ((cls.low, 40), (cls.high, 80), (cls.absent, 50)):
            Score.objects.create(
                exam=cls.exam, student=student, total_score=Decimal(total), is_taken=True
            )

    def eligibility(self, student):
        return ClinicEligibility.objects.get(exam=self.exam, student=student)

    def test_a_present_student_below_the_average_is_a_target(self):
        self.assertEqual(scoring.mark_clinic_targets(self.exam), 1)

        row = self.eligibility(self.low)
        self.assertTrue(row.is_target)
        self.assertIsNone(row.reason)
        # 판정에 쓴 기준점을 남긴다 — 평균 (40+80+50)/3
        self.assertAlmostEqual(float(row.cutoff_score), (40 + 80 + 50) / 3, places=2)

    def test_a_student_above_the_average_is_not(self):
        scoring.mark_clinic_targets(self.exam)

        row = self.eligibility(self.high)
        self.assertFalse(row.is_target)
        self.assertEqual(row.reason, ClinicEligibility.Reason.ABOVE_AVG)

    def test_an_absent_student_is_not(self):
        """점수가 아무리 낮아도 그 자리에 없었으면 대상이 아니다."""
        scoring.mark_clinic_targets(self.exam)

        row = self.eligibility(self.absent)
        self.assertFalse(row.is_target)
        self.assertEqual(row.reason, ClinicEligibility.Reason.ABSENT)

    def test_a_student_who_did_not_sit_the_exam_is_not(self):
        scoring.finalize_exam(self.exam)

        row = self.eligibility(self.skipped)
        self.assertFalse(row.is_target)
        self.assertEqual(row.reason, ClinicEligibility.Reason.NOT_TAKEN)

    def test_finalize_makes_the_call(self):
        """채점이 끝나는 자리마다 판정이 선다 — 시드 밖에서도."""
        scoring.finalize_exam(self.exam)

        self.assertEqual(ClinicEligibility.objects.filter(exam=self.exam).count(), 4)
        self.assertEqual(
            ClinicEligibility.objects.filter(exam=self.exam, is_target=True).count(), 1
        )

    def test_running_twice_does_not_duplicate(self):
        scoring.finalize_exam(self.exam)
        scoring.finalize_exam(self.exam)

        self.assertEqual(ClinicEligibility.objects.filter(exam=self.exam).count(), 4)

    def test_it_follows_a_corrected_score(self):
        """보정으로 점수가 바뀌면 판정도 따라 움직인다."""
        scoring.mark_clinic_targets(self.exam)
        Score.objects.filter(exam=self.exam, student=self.high).update(
            total_score=Decimal("10")
        )

        scoring.mark_clinic_targets(self.exam)

        self.assertTrue(self.eligibility(self.high).is_target)

    def test_it_does_not_overwrite_what_a_person_decided(self):
        """사람이 판정한 행은 재채점이 되돌리지 못한다 — 출석과 같은 축."""
        actor = User.objects.create_user(
            login_id="staff-elig", password="pw1234!!", role=User.Role.ADMIN, name="관리자"
        )
        ClinicEligibility.objects.create(
            exam=self.exam, student=self.high, is_target=True, determined_by=actor
        )

        scoring.mark_clinic_targets(self.exam)

        self.assertTrue(self.eligibility(self.high).is_target)

    def test_an_admin_cut_replaces_the_average(self):
        """기준점은 관리자 컷 우선 — 담을 자리가 `avg_score` 뿐이라 지금은 그것이다."""
        Exam.objects.filter(pk=self.exam.pk).update(avg_score=Decimal("30"))

        scoring.mark_clinic_targets(Exam.objects.get(pk=self.exam.pk))

        self.assertFalse(self.eligibility(self.low).is_target)

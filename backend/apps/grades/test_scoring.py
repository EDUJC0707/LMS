"""성적 집계 계약 — 미제출 표기 · 백분위 · 석차 (apps/grades/scoring.py).

`is_taken` 이 "시험 봤나"의 단일 원천이라는 계약을 여기서 고정한다. 예전에는
`attendances.exam_taken` 과 두 곳에 갈려 있었고, **운영에서는 미제출 성적 행을
아무도 안 만들어서** 답안지를 안 낸 학생이 성적 화면에 아예 없었다.
"""
import datetime
from decimal import Decimal

from django.test import TestCase

from apps.curriculum.models import Course, CourseWeek

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

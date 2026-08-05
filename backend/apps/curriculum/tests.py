"""curriculum 스모크 테스트 — 도메인 3(커리큘럼/일정) 핵심 계약 검증.

설계 근거: docs/db/lms-db-design-2026-07-15.md 도메인 3, §4.4(캘린더 홈 집계),
PRD 3.2.0(캘린더 홈 데이터 소스), PRD §4 상태 기반 노출 원칙(주차 공개 게이팅).
"""
import datetime

from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import Student

from .models import Course, CourseEnrollment, CourseWeek, WeekDayPlan


class CourseTests(TestCase):
    def test_create_course_defaults(self):
        course = Course.objects.create(name="로직엔제")
        self.assertTrue(course.is_active)  # 설계: is_active NN 기본 true
        self.assertIsNone(course.target_grade)  # 설계: NULL 허용
        self.assertIsNotNone(course.created_at)

    def test_table_and_pk_column_follow_design(self):
        # 설계 문서 정렬: db_table=courses, PK 컬럼명=course_id
        self.assertEqual(Course._meta.db_table, "courses")
        self.assertEqual(Course._meta.pk.column, "course_id")


class CourseWeekTests(TestCase):
    def setUp(self):
        self.course = Course.objects.create(name="로직엔제")

    def test_week_no_unique_per_course(self):
        # 설계: UQ(course_id, week_no)
        CourseWeek.objects.create(course=self.course, week_no=1, title="1주차")
        with self.assertRaises(IntegrityError):
            CourseWeek.objects.create(course=self.course, week_no=1)

    def test_same_week_no_allowed_across_courses(self):
        other = Course.objects.create(name="오메가")
        CourseWeek.objects.create(course=self.course, week_no=1)
        CourseWeek.objects.create(course=other, week_no=1)  # 다른 강좌면 허용
        self.assertEqual(CourseWeek.objects.filter(week_no=1).count(), 2)

    def test_offline_notice_for_calendar(self):
        # PRD 3.2.0: 오프라인 특이사항(주차공지) → 캘린더 표기
        week = CourseWeek.objects.create(
            course=self.course, week_no=1, offline_notice="오메가블랙 1회 응시"
        )
        self.assertEqual(week.offline_notice, "오메가블랙 1회 응시")
        self.assertEqual(CourseWeek._meta.db_table, "course_weeks")
        self.assertEqual(CourseWeek._meta.pk.column, "week_id")


class CourseWeekReleaseGatingTests(TestCase):
    """PRD §4 상태 기반 노출(콘텐츠 단위) — `released()` 공개 게이팅 계약.

    계약: 소비자용(학생·학부모) API는 CourseWeek.objects.released()를 거친
    주차만 노출한다. 기준 시각(at)을 고정해 경계를 결정적으로 검증한다.
    """

    def setUp(self):
        self.course = Course.objects.create(name="로직엔제")
        # 기준 시각: 2026-07-22(수) 10:00 KST
        self.at = timezone.make_aware(datetime.datetime(2026, 7, 22, 10, 0))

    def _week(self, no, **kwargs):
        return CourseWeek.objects.create(course=self.course, week_no=no, **kwargs)

    def _released_ids(self):
        return set(
            CourseWeek.objects.released(at=self.at).values_list("week_id", flat=True)
        )

    # --- release_at 명시(관리자 오버라이드) 경계 ---------------------------

    def test_release_at_past_is_released(self):
        week = self._week(1, release_at=self.at - datetime.timedelta(hours=1))
        self.assertIn(week.week_id, self._released_ids())

    def test_release_at_exact_boundary_is_released(self):
        # 공개 시각 도달 시점부터 즉시 공개(<=)
        week = self._week(1, release_at=self.at)
        self.assertIn(week.week_id, self._released_ids())

    def test_release_at_future_is_hidden(self):
        week = self._week(1, release_at=self.at + datetime.timedelta(minutes=1))
        self.assertNotIn(week.week_id, self._released_ids())

    # --- release_at NULL = 주 시작일과 동기화 ------------------------------

    def test_null_release_at_follows_started_start_date(self):
        # 시작일 당일(자정 경과)부터 공개
        week = self._week(1, start_date=datetime.date(2026, 7, 22))
        past_week = self._week(2, start_date=datetime.date(2026, 7, 15))
        released = self._released_ids()
        self.assertIn(week.week_id, released)
        self.assertIn(past_week.week_id, released)

    def test_null_release_at_future_start_date_is_hidden(self):
        week = self._week(1, start_date=datetime.date(2026, 7, 23))
        self.assertNotIn(week.week_id, self._released_ids())

    def test_null_release_at_and_null_start_date_is_hidden(self):
        # 일정 미정 주차는 무기한 비공개(닫힘이 안전 기본값 — PRD §4 목적)
        week = self._week(1)
        self.assertNotIn(week.week_id, self._released_ids())

    # --- 조기 공개 / 연기(release_at 이 start_date 보다 우선) ---------------

    def test_early_release_overrides_future_start_date(self):
        # 다음 주차지만 관리자가 조기 공개 → 노출
        week = self._week(
            1,
            start_date=datetime.date(2026, 7, 27),
            release_at=self.at - datetime.timedelta(days=1),
        )
        self.assertIn(week.week_id, self._released_ids())

    def test_future_release_at_overrides_started_start_date(self):
        # 주가 시작됐어도 release_at 이 미래면 비공개(release_at 우선)
        week = self._week(
            1,
            start_date=datetime.date(2026, 7, 20),
            release_at=self.at + datetime.timedelta(days=1),
        )
        self.assertNotIn(week.week_id, self._released_ids())

    # --- 관리자 화면은 게이팅 없음 -----------------------------------------

    def test_default_manager_still_returns_unreleased_weeks(self):
        self._week(1, start_date=datetime.date(2026, 8, 1))
        self.assertEqual(CourseWeek.objects.count(), 1)


class WeekDayPlanTests(TestCase):
    def setUp(self):
        course = Course.objects.create(name="로직엔제")
        self.week = CourseWeek.objects.create(course=course, week_no=1)

    def test_day_no_unique_per_week(self):
        # 설계: UQ(week_id, day_no)
        WeekDayPlan.objects.create(week=self.week, day_no=1, content="Day1 학습계획")
        with self.assertRaises(IntegrityError):
            WeekDayPlan.objects.create(week=self.week, day_no=1)

    def test_table_and_pk_column_follow_design(self):
        self.assertEqual(WeekDayPlan._meta.db_table, "week_day_plans")
        self.assertEqual(WeekDayPlan._meta.pk.column, "plan_id")


class CourseEnrollmentTests(TestCase):
    def setUp(self):
        self.course = Course.objects.create(name="로직엔제")
        self.student = Student.objects.create(matching_key="24-001")

    def test_status_defaults_to_enrolled(self):
        # 설계: status NN 기본 `수강`, 한국어 TextChoices
        enrollment = CourseEnrollment.objects.create(
            student=self.student, course=self.course
        )
        self.assertEqual(enrollment.status, CourseEnrollment.Status.ENROLLED)
        self.assertEqual(enrollment.status, "수강")
        self.assertIsNotNone(enrollment.enrolled_at)
        self.assertIsNone(enrollment.ended_at)

    def test_student_course_unique(self):
        # 설계: UQ(student_id, course_id) — 캘린더 렌더 근거의 유일성
        CourseEnrollment.objects.create(student=self.student, course=self.course)
        with self.assertRaises(IntegrityError):
            CourseEnrollment.objects.create(student=self.student, course=self.course)

    def test_table_and_pk_column_follow_design(self):
        self.assertEqual(CourseEnrollment._meta.db_table, "course_enrollments")
        self.assertEqual(CourseEnrollment._meta.pk.column, "enrollment_id")

"""인쇄용 성적표 묶음 API 테스트 — 반 일괄·개별 (FLOW 3-11 오프라인).

검증 축:
- 기능 키 게이트: 성적처리(features.py — "OMR 채점·보정·성적표 배부").
  조교 프리셋에는 없다 — 대표가 delta 로 열어 줘야 한다.
- 확정이 성적표를 연다(FLOW 3-11 "확정이 여는 것: 영상 발송·문자 발송·성적표").
  확정 전이면 400, 시험이 없는 회차도 400.
- 일괄은 명단 순서(student_id 오름차순)이고, 성적이 없거나 미응시인 학생은
  빠진다(PRD 3.1.1) — 묶음 수가 명단 수와 다를 수 있다는 뜻이다.
- 개별은 같은 응답의 1건짜리 묶음이다.
- **지면과 화면이 같다**: 관리자가 뽑는 한 건이 그 학생의
  `/api/student/grades/{exam_id}` 응답과 완전히 같아야 한다(FLOW 3-11
  "LMS 에 들어가서 보는 것과 같은 화면").

픽스처: 목반 4명 — s1(60점 응시) · s2(80점 응시) · s3(미응시) · s4(성적 없음).
묶음에 남는 것은 s1·s2 둘뿐이다.
"""
import datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.accounts.features import FeatureKey
from apps.accounts.models import StaffFeatureGrant, Student, User
from apps.curriculum.models import Class, Course, CourseEnrollment, CourseWeek

from .models import ClassSession, Exam, Score

PASSWORD = "pw-Secret-77!"
CONFIRMED_AT = timezone.make_aware(datetime.datetime(2026, 7, 22, 22, 0))


def make_user(login_id, role, name="사용자"):
    return User.objects.create_user(login_id=login_id, password=PASSWORD, name=name, role=role)


def make_student(login_id, name):
    user = make_user(login_id, User.Role.STUDENT, name=name)
    return Student.objects.create(
        user=user,
        matching_key=f"uid-{login_id}",
        enrollment_status=Student.EnrollmentStatus.REGISTERED,
    )


class SessionReportApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user("rep-owner", User.Role.OWNER, name="대표")
        cls.assistant = make_user("rep-assist", User.Role.ASSISTANT, name="조교")

        cls.course = Course.objects.create(name="로직엔제")
        cls.klass = Class.objects.create(course=cls.course, name="목반")
        cls.week = CourseWeek.objects.create(
            course=cls.course, week_no=3, title="3주차", start_date=datetime.date(2026, 7, 20)
        )
        cls.exam = Exam.objects.create(
            name="오메가블랙 3회", exam_date=datetime.date(2026, 7, 22), round_no=3
        )
        cls.session = ClassSession.objects.create(
            session_date=datetime.date(2026, 7, 22),
            session_no=3,
            course_week=cls.week,
            klass=cls.klass,
            week_no=3,
            exam=cls.exam,
            confirmed_at=CONFIRMED_AT,
        )
        # 시험이 붙지 않은 회차 — 뽑을 것이 없다
        cls.session_noexam = ClassSession.objects.create(
            session_date=datetime.date(2026, 7, 29),
            session_no=4,
            course_week=cls.week,
            klass=cls.klass,
            week_no=4,
            confirmed_at=CONFIRMED_AT,
        )
        # 확정 전 회차 — 성적표는 확정이 연다
        cls.session_unconfirmed = ClassSession.objects.create(
            session_date=datetime.date(2026, 8, 5),
            session_no=5,
            course_week=cls.week,
            klass=cls.klass,
            week_no=5,
            exam=cls.exam,
        )

        cls.s1 = make_student("rep-s1", "김서연")
        cls.s2 = make_student("rep-s2", "이준호")
        cls.s3 = make_student("rep-s3", "박민지")
        cls.s4 = make_student("rep-s4", "최하늘")
        for student in (cls.s1, cls.s2, cls.s3, cls.s4):
            CourseEnrollment.objects.create(
                student=student, course=cls.course, klass=cls.klass
            )

        Score.objects.create(
            exam=cls.exam, student=cls.s1, total_score=Decimal("60"),
            max_score=Decimal("100"), is_taken=True,
        )
        Score.objects.create(
            exam=cls.exam, student=cls.s2, total_score=Decimal("80"),
            max_score=Decimal("100"), is_taken=True,
        )
        # s3 미응시 — 성적표를 만들지 않는다(PRD 3.1.1). s4 는 성적 행 자체가 없다.
        Score.objects.create(
            exam=cls.exam, student=cls.s3, total_score=None,
            max_score=Decimal("100"), is_taken=False,
        )

    def url(self, session=None):
        return f"/api/admin/attendance/sessions/{(session or self.session).session_id}/reports"

    def test_feature_gate_is_grade_processing(self):
        """조교 프리셋에는 성적처리가 없다 — 대표가 delta 로 열어야 뽑힌다."""
        self.client.force_login(self.assistant)
        self.assertEqual(self.client.get(self.url()).status_code, 403)

        StaffFeatureGrant.objects.create(
            user=self.assistant, feature_key=FeatureKey.GRADE_PROCESSING, is_granted=True
        )
        self.assertEqual(self.client.get(self.url()).status_code, 200)

    def test_unconfirmed_session_refuses(self):
        """확정이 성적표를 연다(FLOW 3-11) — 그 전에는 400."""
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(self.url(self.session_unconfirmed)).status_code, 400)

    def test_session_without_exam_refuses(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(self.url(self.session_noexam)).status_code, 400)

    def test_bulk_is_roster_order_without_empty_sheets(self):
        """반 일괄 — 명단 순서 그대로, 미응시·성적 없음은 장을 만들지 않는다."""
        self.client.force_login(self.owner)
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 200)
        reports = response.json()["reports"]
        self.assertEqual(
            [r["student"]["student_id"] for r in reports],
            [self.s1.student_id, self.s2.student_id],
        )
        self.assertTrue(all(r["report"] for r in reports))

    def test_single_student_is_the_same_bundle(self):
        """개별 프린트 = 같은 응답의 1건. 명단 밖 학생은 빈 묶음이다."""
        self.client.force_login(self.owner)
        one = self.client.get(self.url(), {"student_id": self.s2.student_id}).json()
        self.assertEqual(len(one["reports"]), 1)
        self.assertEqual(one["reports"][0]["student"]["student_id"], self.s2.student_id)

        outsider = make_student("rep-out", "남의반")
        self.assertEqual(
            self.client.get(self.url(), {"student_id": outsider.student_id}).json()["reports"],
            [],
        )

    def test_printed_sheet_equals_the_students_own_screen(self):
        """지면과 화면이 같은 것을 말한다(FLOW 3-11) — 같은 조립 함수를 쓴다."""
        self.client.force_login(self.owner)
        printed = self.client.get(self.url(), {"student_id": self.s1.student_id}).json()[
            "reports"
        ][0]

        self.client.force_login(self.s1.user)
        on_screen = self.client.get(f"/api/student/grades/{self.exam.exam_id}").json()
        self.assertEqual(printed, on_screen)

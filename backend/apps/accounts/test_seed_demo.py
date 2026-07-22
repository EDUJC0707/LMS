"""seed_demo 관리 커맨드 테스트 — 데모·개발용 시드 데이터 (기능 전시 환경).

검증 축:
- 계정: 직원 3(대표/관리자/조교) + 학생 30(등록 28·예비등록 2) + 학부모 10,
  전원 test1234 로그인 가능·must_change_password=False
- 커리큘럼: 강좌 1 + 주차 10(오늘 기준 4주차까지만 공개 — 게이팅) + Day 계획
- 출결: 회차(수·토) + 지난 회차 출결(출석/결석/지각 혼합) → 트리거 파생
  (VideoGrant source=출석자동, AbsenceCounseling 대기열)이 실제 생성됨
- 성적: 시험 3 × 문항 20(테마·오답 가이드 포함) + 답안·점수(일부 미응시)
- 클리닉: 슬롯 5(월~금) + 자격 판정 + 신청(대기·승인배정 혼합)
- 게시판·결제·워크북·알림: 카테고리별 글(비밀글 포함)·교재 1+주문 혼합·
  확정 워크북·알림 행
- 멱등: 2회 실행해도 카운트 동일(초기화 후 재생성)
"""
import io

from django.core.management import call_command
from django.test import TestCase

from apps.accounts.models import Parent, ParentStudent, Student, User
from apps.boards.models import AbsenceCounseling, Post
from apps.clinic.models import ClinicEligibility, ClinicRequest, ClinicSlot
from apps.curriculum.models import Course, CourseWeek, WeekDayPlan
from apps.grades.models import (
    Attendance,
    ClassSession,
    Exam,
    Question,
    Score,
    WorkbookSubmission,
)
from apps.notifications.models import Notification
from apps.payments.models import Order, Product
from apps.videos.models import VideoGrant


def run_seed():
    out = io.StringIO()
    call_command("seed_demo", stdout=out)
    return out.getvalue()


class SeedDemoTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.output = run_seed()

    def test_staff_accounts_created(self):
        self.assertEqual(User.objects.filter(role=User.Role.OWNER).count(), 1)
        self.assertEqual(User.objects.filter(role=User.Role.ADMIN).count(), 1)
        self.assertEqual(User.objects.filter(role=User.Role.ASSISTANT).count(), 1)
        owner = User.objects.get(role=User.Role.OWNER)
        self.assertEqual(owner.login_id, "01000000001")
        self.assertTrue(owner.check_password("test1234"))
        self.assertFalse(owner.must_change_password)

    def test_students_and_parents_created(self):
        self.assertEqual(Student.objects.count(), 30)
        self.assertEqual(
            Student.objects.filter(
                enrollment_status=Student.EnrollmentStatus.REGISTERED
            ).count(),
            28,
        )
        self.assertEqual(
            Student.objects.filter(
                enrollment_status=Student.EnrollmentStatus.PRE_REGISTERED
            ).count(),
            2,
        )
        self.assertEqual(Parent.objects.count(), 10)
        # 학부모마다 자녀 1~2명 연동
        for parent in Parent.objects.all():
            links = ParentStudent.objects.filter(parent=parent).count()
            self.assertIn(links, (1, 2))
        # 학생 전원 test1234 로그인 조건
        student_user = Student.objects.order_by("student_id").first().user
        self.assertTrue(student_user.check_password("test1234"))
        self.assertFalse(student_user.must_change_password)

    def test_curriculum_created_with_gating(self):
        self.assertEqual(Course.objects.count(), 1)
        self.assertEqual(CourseWeek.objects.count(), 10)
        # 오늘 기준 4주차까지만 공개(5주차부터 미공개 — 게이팅 시연)
        self.assertEqual(CourseWeek.objects.released().count(), 4)
        self.assertTrue(WeekDayPlan.objects.exists())
        # 주차 공지(오프라인 특이사항) 최소 1건
        self.assertTrue(CourseWeek.objects.filter(offline_notice__isnull=False).exists())

    def test_sessions_and_attendance_with_triggers(self):
        self.assertTrue(ClassSession.objects.exists())
        statuses = set(Attendance.objects.values_list("status", flat=True))
        self.assertEqual(statuses, {"출석", "결석", "지각"})
        # 출석 트리거 — 영상 권한 자동 지급
        self.assertTrue(
            VideoGrant.objects.filter(source=VideoGrant.Source.ATTENDANCE_AUTO).exists()
        )
        # 결석 트리거 — 상담 대기열
        self.assertTrue(
            AbsenceCounseling.objects.filter(
                status=AbsenceCounseling.Status.PENDING
            ).exists()
        )

    def test_exams_scores_and_report_material(self):
        self.assertEqual(Exam.objects.count(), 3)
        for exam in Exam.objects.all():
            self.assertEqual(exam.questions.count(), 20)
        # 성적표 섹션 재료 — 테마·오답 가이드
        self.assertTrue(Question.objects.filter(theme_tag__isnull=False).exists())
        self.assertTrue(Question.objects.filter(study_guide__isnull=False).exists())
        # 일부 학생 미응시
        self.assertTrue(Score.objects.filter(is_taken=False).exists())
        self.assertTrue(Score.objects.filter(is_taken=True).exists())

    def test_clinic_seeded(self):
        self.assertEqual(ClinicSlot.objects.count(), 5)
        self.assertEqual(
            sorted(ClinicSlot.objects.values_list("weekday", flat=True)), [1, 2, 3, 4, 5]
        )
        self.assertTrue(ClinicEligibility.objects.filter(is_target=True).exists())
        req_statuses = set(ClinicRequest.objects.values_list("status", flat=True))
        self.assertIn(ClinicRequest.Status.PENDING, req_statuses)
        self.assertIn(ClinicRequest.Status.APPROVED, req_statuses)

    def test_boards_payments_workbook_notifications(self):
        for category in Post.Category.values:
            self.assertGreaterEqual(
                Post.objects.filter(category=category).count(), 2, category
            )
        self.assertTrue(Post.objects.filter(is_secret=True).exists())
        self.assertEqual(Product.objects.count(), 1)
        order_statuses = set(Order.objects.values_list("status", flat=True))
        self.assertIn(Order.Status.UNPAID, order_statuses)
        self.assertIn(Order.Status.PAID, order_statuses)
        # 소비자 노출 대상(매핑 확정) 워크북 존재
        self.assertTrue(
            WorkbookSubmission.objects.filter(
                match_status__in=("자동매칭", "수동확정")
            ).exists()
        )
        self.assertTrue(Notification.objects.exists())

    def test_output_lists_login_accounts(self):
        self.assertIn("01000000001", self.output)
        self.assertIn("test1234", self.output)

    def test_idempotent_rerun(self):
        before = (
            User.objects.count(),
            Student.objects.count(),
            Attendance.objects.count(),
            Exam.objects.count(),
            Post.objects.count(),
        )
        run_seed()
        after = (
            User.objects.count(),
            Student.objects.count(),
            Attendance.objects.count(),
            Exam.objects.count(),
            Post.objects.count(),
        )
        self.assertEqual(before, after)

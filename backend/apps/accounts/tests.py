"""accounts 스모크 테스트 — 도메인 1 핵심 계약 검증."""
from django.db import IntegrityError
from django.test import TestCase

from .models import Parent, ParentStudent, Student, User


class UserManagerTests(TestCase):
    def test_create_user_hashes_password(self):
        user = User.objects.create_user(
            login_id="hong123", password="raw-pass-1!", name="홍길동", role=User.Role.STUDENT
        )
        self.assertNotEqual(user.password, "raw-pass-1!")
        self.assertTrue(user.check_password("raw-pass-1!"))
        self.assertTrue(user.must_change_password)  # 일괄생성 기본값

    def test_create_superuser_role_and_flags(self):
        admin = User.objects.create_superuser(login_id="boss", password="pw-boss-1!", name="대표님")
        self.assertEqual(admin.role, User.Role.OWNER)
        self.assertFalse(admin.must_change_password)
        self.assertTrue(admin.is_superuser)
        self.assertTrue(admin.is_staff)  # role 기반 property

    def test_set_password_updates_password_changed_at(self):
        user = User(login_id="p1", name="학부모", role=User.Role.PARENT)
        self.assertIsNone(user.password_changed_at)
        user.set_password("new-pass-2!")
        self.assertIsNotNone(user.password_changed_at)

    def test_create_user_without_role_rejected(self):
        # role='' 유령 계정 차단 — DB CHECK를 두지 않는 설계라 매니저가 막는다.
        with self.assertRaises(ValueError):
            User.objects.create_user("norole", "pw-1234!", name="역할없음")

    def test_student_role_is_not_staff(self):
        user = User.objects.create_user(
            login_id="stu1", password="pw", name="학생", role=User.Role.STUDENT
        )
        self.assertFalse(user.is_staff)


class StudentTests(TestCase):
    def test_enrollment_status_defaults_to_pre_registered(self):
        student = Student.objects.create(unique_id="24-001")
        self.assertEqual(student.enrollment_status, Student.EnrollmentStatus.PRE_REGISTERED)
        self.assertIsNone(student.user)  # 명단 선입력 — 계정보다 사람 행이 먼저


class ParentStudentTests(TestCase):
    def test_duplicate_parent_student_rejected(self):
        parent = Parent.objects.create(phone="010-1234-5678")
        student = Student.objects.create(unique_id="24-002")
        ParentStudent.objects.create(parent=parent, student=student, relation="모")
        with self.assertRaises(IntegrityError):
            ParentStudent.objects.create(parent=parent, student=student, relation="부")

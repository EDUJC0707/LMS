"""accounts 스모크 테스트 — 도메인 1 핵심 계약 검증."""
from django.db import IntegrityError
from django.test import TestCase

from .features import OWNER_ONLY_FEATURES, ROLE_PRESETS, FeatureKey, effective_features
from .models import Parent, ParentStudent, StaffFeatureGrant, Student, User


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
        student = Student.objects.create(matching_key="24-001")
        self.assertEqual(student.enrollment_status, Student.EnrollmentStatus.PRE_REGISTERED)
        self.assertIsNone(student.user)  # 명단 선입력 — 계정보다 사람 행이 먼저


class ParentStudentTests(TestCase):
    def test_duplicate_parent_student_rejected(self):
        parent = Parent.objects.create(phone="010-1234-5678")
        student = Student.objects.create(matching_key="24-002")
        ParentStudent.objects.create(parent=parent, student=student, relation="모")
        with self.assertRaises(IntegrityError):
            ParentStudent.objects.create(parent=parent, student=student, relation="부")


class YoutubeCleanupTests(TestCase):
    def test_student_youtube_email_removed(self):
        # PRD 3.1.3(2026-07-21 유튜브 폐기): 종속 컬럼 정리 시점 이행
        field_names = {f.name for f in Student._meta.get_fields()}
        self.assertNotIn("youtube_email", field_names)


class ParentCredentialsTests(TestCase):
    def test_credentials_sent_at_null_until_batch(self):
        # D-1 계정 발급 배치의 대상 판정(students 와 동일 패턴) — 발송 전 NULL
        parent = Parent.objects.create(phone="010-1234-5678")
        self.assertIsNone(parent.credentials_sent_at)


def make_staff(login_id, role):
    return User.objects.create_user(login_id=login_id, password="pw-1!", name="직원", role=role)


class StaffFeatureGrantTests(TestCase):
    def test_table_follows_design(self):
        self.assertEqual(StaffFeatureGrant._meta.db_table, "staff_feature_grants")

    def test_user_feature_key_unique(self):
        # UQ(user, feature_key) — 직원당 기능 키 delta 1줄
        staff = make_staff("adm1", User.Role.ADMIN)
        StaffFeatureGrant.objects.create(
            user=staff, feature_key=FeatureKey.GRADE_PROCESSING, is_granted=True
        )
        with self.assertRaises(IntegrityError):
            StaffFeatureGrant.objects.create(
                user=staff, feature_key=FeatureKey.GRADE_PROCESSING, is_granted=False
            )

    def test_feature_key_is_open_value_set(self):
        # 개방 값집합(notifications.type 선례) — choices 를 필드에 바인딩하지 않는다
        field = StaffFeatureGrant._meta.get_field("feature_key")
        self.assertIsNone(field.choices)


class EffectiveFeaturesTests(TestCase):
    """프리셋 ⊕ delta(2026-07-22 확정, PRD §4 직원 기능 권한) 계약."""

    def test_assistant_preset_covers_the_class_page(self):
        # FLOW §3: 반별 관리에서 손을 움직이는 것은 조교다. 출결입력이 없으면
        # 페이지 자체가 안 열린다(2026-08-18). 결제·성적·권한부여는 여전히 없다.
        assistant = make_staff("as1", User.Role.ASSISTANT)
        self.assertEqual(
            effective_features(assistant),
            {
                FeatureKey.ATTENDANCE_ENTRY,
                FeatureKey.WORKBOOK_UPLOAD,
                FeatureKey.CLINIC_ASSIGN,
            },
        )

    def test_admin_preset_covers_operations_but_not_grant_admin(self):
        # PRD 2장: 관리자 = 운영 전반. 권한부여는 대표 전용 후보(key_considerations §2)
        # 라 프리셋에 없다 — 대표가 개별 부여로만 열 수 있다.
        admin = make_staff("adm2", User.Role.ADMIN)
        features = effective_features(admin)
        self.assertIn(FeatureKey.GRADE_PROCESSING, features)
        self.assertIn(FeatureKey.ATTENDANCE_ENTRY, features)
        self.assertIn(FeatureKey.VIDEO_GRANT_ADMIN, features)
        self.assertIn(FeatureKey.PAYMENT_CHECK, features)
        self.assertNotIn(FeatureKey.FEATURE_GRANT_ADMIN, features)

    def test_delta_grant_adds_to_preset(self):
        # is_granted=true → 프리셋에 추가
        assistant = make_staff("as2", User.Role.ASSISTANT)
        StaffFeatureGrant.objects.create(
            user=assistant, feature_key=FeatureKey.ATTENDANCE_ENTRY, is_granted=True
        )
        self.assertIn(FeatureKey.ATTENDANCE_ENTRY, effective_features(assistant))

    def test_delta_revoke_removes_from_preset(self):
        # is_granted=false → 프리셋에서 회수
        assistant = make_staff("as3", User.Role.ASSISTANT)
        StaffFeatureGrant.objects.create(
            user=assistant, feature_key=FeatureKey.WORKBOOK_UPLOAD, is_granted=False
        )
        self.assertNotIn(FeatureKey.WORKBOOK_UPLOAD, effective_features(assistant))

    def test_owner_has_all_features(self):
        # 대표는 전권 — delta 무관
        owner = make_staff("own1", User.Role.OWNER)
        StaffFeatureGrant.objects.create(
            user=owner, feature_key=FeatureKey.GRADE_PROCESSING, is_granted=False
        )
        self.assertEqual(effective_features(owner), set(FeatureKey))

    def test_non_staff_roles_have_no_features(self):
        # 소비자(학생·학부모)는 직원 기능 없음 — 닫힘이 기본값
        student = make_staff("stu9", User.Role.STUDENT)
        parent = make_staff("par9", User.Role.PARENT)
        self.assertEqual(effective_features(student), set())
        self.assertEqual(effective_features(parent), set())

    def test_role_presets_cover_admin_and_assistant(self):
        self.assertIn(User.Role.ADMIN, ROLE_PRESETS)
        self.assertIn(User.Role.ASSISTANT, ROLE_PRESETS)

    def test_owner_only_placeholder_is_empty(self):
        # 대표 전용 범위는 추후 결정(key_considerations §2) — 자리만, 값은 비움
        self.assertEqual(OWNER_ONLY_FEATURES, frozenset())

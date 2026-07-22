"""권한 매트릭스·직원 계정 API 8차 슬라이스 테스트 — PRD §4 직원 기능 권한.

검증 축:
- 대표 전용 강제(role=대표만): 관리자·조교는 **권한부여 delta 를 받아도** 403
  (기능 키가 아니라 역할 게이트 — 과제 명세)
- GET 매트릭스: 프리셋/delta(추가·회수)/유효 기능 구분 표시
- PUT features: {feature_key: bool} 맵 upsert + **프리셋과 같으면 delta 행
  삭제(최소 delta)** + granted_by 기록 + 자기 자신·대표 대상 400
- POST 직원 생성: login_id=전화번호·랜덤 초기 비번·must_change_password
- PATCH deactivate: is_active=false (대표 대상 400)
"""
import json

from django.test import TestCase

from .features import ROLE_PRESETS, FeatureKey
from .models import StaffFeatureGrant, User

PASSWORD = "pw-Secret-77!"
STAFF_URL = "/api/admin/staff"


def make_user(login_id, role, name="사용자", **extra):
    return User.objects.create_user(
        login_id=login_id, password=PASSWORD, name=name, role=role, **extra
    )


class StaffAdminFixtureMixin:
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user("st-own", User.Role.OWNER, name="대표")
        cls.owner2 = make_user("st-own2", User.Role.OWNER, name="대표2")
        cls.admin = make_user("st-adm", User.Role.ADMIN, name="관리자A")
        cls.assistant = make_user("st-ast", User.Role.ASSISTANT, name="조교B")
        cls.student = make_user("st-stu", User.Role.STUDENT, name="학생C")

    def put_features(self, target, body):
        return self.client.put(
            f"{STAFF_URL}/{target.user_id}/features",
            data=json.dumps(body),
            content_type="application/json",
        )


class StaffMatrixOwnerOnlyTests(StaffAdminFixtureMixin, TestCase):
    """대표 전용 강제 — 관리자(권한부여 delta 보유해도)·조교·학생 전부 403."""

    def test_admin_gets_403_even_with_feature_grant_delta(self):
        StaffFeatureGrant.objects.create(
            user=self.admin,
            feature_key=FeatureKey.FEATURE_GRANT_ADMIN,
            is_granted=True,
            granted_by=self.owner,
        )
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(STAFF_URL).status_code, 403)
        self.assertEqual(
            self.put_features(self.assistant, {FeatureKey.GRADE_PROCESSING: True}).status_code,
            403,
        )
        self.assertEqual(self.client.post(STAFF_URL, {}).status_code, 403)
        self.assertEqual(
            self.client.patch(f"{STAFF_URL}/{self.assistant.user_id}/deactivate").status_code,
            403,
        )

    def test_assistant_and_student_get_403(self):
        for user in (self.assistant, self.student):
            self.client.force_login(user)
            self.assertEqual(self.client.get(STAFF_URL).status_code, 403)

    def test_anonymous_gets_403(self):
        self.assertEqual(self.client.get(STAFF_URL).status_code, 403)


class StaffMatrixListTests(StaffAdminFixtureMixin, TestCase):
    """GET /api/admin/staff — 직원 목록 + 프리셋/delta 구분 표시."""

    def setUp(self):
        self.client.force_login(self.owner)

    def test_lists_admin_and_assistant_only(self):
        body = self.client.get(STAFF_URL).json()
        ids = {row["user_id"] for row in body["staff"]}
        self.assertEqual(ids, {self.admin.user_id, self.assistant.user_id})
        self.assertEqual(sorted(body["feature_keys"]), sorted(FeatureKey.values))

    def test_matrix_row_shows_preset_delta_effective(self):
        StaffFeatureGrant.objects.create(
            user=self.admin,
            feature_key=FeatureKey.GRADE_PROCESSING,
            is_granted=False,
            granted_by=self.owner,
        )
        StaffFeatureGrant.objects.create(
            user=self.assistant,
            feature_key=FeatureKey.NOTICE_WRITE,
            is_granted=True,
            granted_by=self.owner,
        )
        rows = {row["user_id"]: row for row in self.client.get(STAFF_URL).json()["staff"]}
        adm = rows[self.admin.user_id]
        self.assertIn(FeatureKey.GRADE_PROCESSING, adm["preset"])
        self.assertIn(FeatureKey.GRADE_PROCESSING, adm["delta"]["removed"])
        self.assertNotIn(FeatureKey.GRADE_PROCESSING, adm["effective"])
        ast = rows[self.assistant.user_id]
        self.assertEqual(sorted(ast["preset"]), sorted(ROLE_PRESETS[User.Role.ASSISTANT]))
        self.assertIn(FeatureKey.NOTICE_WRITE, ast["delta"]["added"])
        self.assertIn(FeatureKey.NOTICE_WRITE, ast["effective"])
        self.assertTrue(adm["is_active"])


class StaffFeaturesPutTests(StaffAdminFixtureMixin, TestCase):
    """PUT /api/admin/staff/{user_id}/features — upsert + 최소 delta."""

    def setUp(self):
        self.client.force_login(self.owner)

    def test_grant_off_preset_key_creates_delta_with_granted_by(self):
        res = self.put_features(self.assistant, {FeatureKey.GRADE_PROCESSING: True})
        self.assertEqual(res.status_code, 200)
        grant = StaffFeatureGrant.objects.get(
            user=self.assistant, feature_key=FeatureKey.GRADE_PROCESSING
        )
        self.assertTrue(grant.is_granted)
        self.assertEqual(grant.granted_by, self.owner)
        self.assertIn(FeatureKey.GRADE_PROCESSING, res.json()["effective"])

    def test_revoke_preset_key_creates_negative_delta(self):
        res = self.put_features(self.admin, {FeatureKey.GRADE_PROCESSING: False})
        self.assertEqual(res.status_code, 200)
        grant = StaffFeatureGrant.objects.get(
            user=self.admin, feature_key=FeatureKey.GRADE_PROCESSING
        )
        self.assertFalse(grant.is_granted)
        self.assertNotIn(FeatureKey.GRADE_PROCESSING, res.json()["effective"])

    def test_value_equal_to_preset_deletes_delta_row(self):
        """최소 delta 유지 — 프리셋과 같아지면 행을 지워 정리한다."""
        StaffFeatureGrant.objects.create(
            user=self.admin,
            feature_key=FeatureKey.GRADE_PROCESSING,
            is_granted=False,
            granted_by=self.owner,
        )
        res = self.put_features(self.admin, {FeatureKey.GRADE_PROCESSING: True})
        self.assertEqual(res.status_code, 200)
        self.assertFalse(
            StaffFeatureGrant.objects.filter(
                user=self.admin, feature_key=FeatureKey.GRADE_PROCESSING
            ).exists()
        )

    def test_value_equal_to_preset_without_row_creates_nothing(self):
        res = self.put_features(self.assistant, {FeatureKey.GRADE_PROCESSING: False})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(StaffFeatureGrant.objects.filter(user=self.assistant).count(), 0)

    def test_upsert_updates_existing_row_not_duplicates(self):
        self.put_features(self.assistant, {FeatureKey.GRADE_PROCESSING: True})
        self.put_features(self.assistant, {FeatureKey.GRADE_PROCESSING: True})
        self.assertEqual(
            StaffFeatureGrant.objects.filter(
                user=self.assistant, feature_key=FeatureKey.GRADE_PROCESSING
            ).count(),
            1,
        )

    def test_owner_target_and_self_target_rejected(self):
        self.assertEqual(
            self.put_features(self.owner2, {FeatureKey.GRADE_PROCESSING: True}).status_code, 400
        )
        self.assertEqual(
            self.put_features(self.owner, {FeatureKey.GRADE_PROCESSING: True}).status_code, 400
        )
        self.assertEqual(StaffFeatureGrant.objects.count(), 0)

    def test_student_target_404(self):
        self.assertEqual(
            self.put_features(self.student, {FeatureKey.GRADE_PROCESSING: True}).status_code,
            404,
        )

    def test_invalid_body_rejected(self):
        res = self.client.put(
            f"{STAFF_URL}/{self.admin.user_id}/features",
            data=json.dumps([FeatureKey.GRADE_PROCESSING]),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(
            self.put_features(self.admin, {FeatureKey.GRADE_PROCESSING: "yes"}).status_code, 400
        )
        self.assertEqual(self.put_features(self.admin, {"": True}).status_code, 400)


class StaffCreateTests(StaffAdminFixtureMixin, TestCase):
    """POST /api/admin/staff — login_id=전화번호·랜덤 초기 비번."""

    def setUp(self):
        self.client.force_login(self.owner)

    def post_staff(self, body):
        return self.client.post(
            STAFF_URL, data=json.dumps(body), content_type="application/json"
        )

    def test_creates_admin_with_phone_login_and_random_password(self):
        res = self.post_staff({"name": "신입관리자", "phone": "01055556666", "role": "관리자"})
        self.assertEqual(res.status_code, 201)
        body = res.json()
        created = User.objects.get(login_id="01055556666")
        self.assertEqual(created.role, User.Role.ADMIN)
        self.assertEqual(created.phone, "01055556666")
        self.assertTrue(created.must_change_password)
        self.assertTrue(created.check_password(body["initial_password"]))

    def test_creates_assistant(self):
        res = self.post_staff({"name": "신입조교", "phone": "01077778888", "role": "조교"})
        self.assertEqual(res.status_code, 201)
        self.assertEqual(User.objects.get(login_id="01077778888").role, User.Role.ASSISTANT)

    def test_owner_role_rejected(self):
        res = self.post_staff({"name": "대표둘", "phone": "01000000001", "role": "대표"})
        self.assertEqual(res.status_code, 400)

    def test_duplicate_login_id_rejected(self):
        make_user("01099990000", User.Role.ADMIN)
        res = self.post_staff({"name": "중복", "phone": "01099990000", "role": "관리자"})
        self.assertEqual(res.status_code, 400)

    def test_missing_fields_rejected(self):
        self.assertEqual(self.post_staff({"name": "무전화", "role": "관리자"}).status_code, 400)
        self.assertEqual(self.post_staff({"phone": "0102223333", "role": "조교"}).status_code, 400)


class StaffDeactivateTests(StaffAdminFixtureMixin, TestCase):
    """PATCH /api/admin/staff/{user_id}/deactivate — is_active=false."""

    def setUp(self):
        self.client.force_login(self.owner)

    def test_deactivates_staff(self):
        res = self.client.patch(f"{STAFF_URL}/{self.admin.user_id}/deactivate")
        self.assertEqual(res.status_code, 200)
        self.admin.refresh_from_db()
        self.assertFalse(self.admin.is_active)

    def test_owner_target_rejected(self):
        res = self.client.patch(f"{STAFF_URL}/{self.owner2.user_id}/deactivate")
        self.assertEqual(res.status_code, 400)

    def test_unknown_target_404(self):
        res = self.client.patch(f"{STAFF_URL}/999999/deactivate")
        self.assertEqual(res.status_code, 404)

"""계정 일괄 발급·등록 전환 API 8차 슬라이스 테스트 — PRD 3.1.5·8-3·8-4.

검증 축:
- 기능 게이트: 계정관리 키(FeatureRequired) — 조교 프리셋에 없어 403,
  delta 부여 시 허용
- 일괄 발급: 학생 User(아이디=전화번호·랜덤 비번·must_change_password) +
  Student(예비등록) / parent_phone → 학부모 계정 생성·**중복 전화면 기존
  학부모에 자녀 연결만**(ParentStudent) / **무전화 학생은 학부모번호+접미사**
  (8-4: a, b, …) / login_id 중복은 **해당 행만 실패**(행 단위 savepoint —
  성공 행은 유지) / 초기 비밀번호는 응답으로 반환·credentials_sent_at 미스탬프
- 등록 전환: 예비등록→등록 + registered_at (그 외 상태 400)
"""
import json

from django.test import TestCase

from .features import FeatureKey
from .models import Parent, ParentStudent, StaffFeatureGrant, Student, User

PASSWORD = "pw-Secret-77!"
BULK_URL = "/api/admin/accounts/bulk"


def make_user(login_id, role, name="사용자", **extra):
    return User.objects.create_user(
        login_id=login_id, password=PASSWORD, name=name, role=role, **extra
    )


class ProvisioningFixtureMixin:
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user("pv-own", User.Role.OWNER, name="대표")
        cls.admin = make_user("pv-adm", User.Role.ADMIN, name="관리자")
        cls.assistant = make_user("pv-ast", User.Role.ASSISTANT, name="조교")

    def post_bulk(self, rows, user=None):
        self.client.force_login(user or self.admin)
        return self.client.post(
            BULK_URL, data=json.dumps(rows), content_type="application/json"
        )


class BulkFeatureGateTests(ProvisioningFixtureMixin, TestCase):
    """계정관리 기능 키 게이트 — 프리셋 ⊕ delta."""

    def test_assistant_without_feature_gets_403(self):
        self.assertEqual(self.post_bulk([], user=self.assistant).status_code, 403)

    def test_assistant_with_delta_passes_gate(self):
        StaffFeatureGrant.objects.create(
            user=self.assistant,
            feature_key=FeatureKey.ACCOUNT_ADMIN,
            is_granted=True,
            granted_by=self.owner,
        )
        # 게이트는 통과하고 빈 명단 검증(400)까지 도달한다.
        self.assertEqual(self.post_bulk([], user=self.assistant).status_code, 400)

    def test_student_role_gets_403(self):
        student_user = make_user("pv-stu", User.Role.STUDENT)
        self.assertEqual(self.post_bulk([], user=student_user).status_code, 403)


class BulkIssueTests(ProvisioningFixtureMixin, TestCase):
    """POST /api/admin/accounts/bulk — 생성·연결·행 단위 실패."""

    def test_creates_student_and_parent_accounts(self):
        rows = [
            {
                "name": "김학생",
                "phone": "01011112222",
                "parent_phone": "01033334444",
                "grade": "고3",
                "school": "한종철고",
                "unique_id": "3_2222",
            }
        ]
        res = self.post_bulk(rows)
        self.assertEqual(res.status_code, 200)
        body = res.json()
        result = body["results"][0]
        self.assertEqual(result["status"], "생성")

        student_user = User.objects.get(login_id="01011112222")
        self.assertEqual(student_user.role, User.Role.STUDENT)
        self.assertEqual(student_user.name, "김학생")
        self.assertTrue(student_user.must_change_password)
        self.assertTrue(student_user.check_password(result["initial_password"]))

        student = Student.objects.get(user=student_user)
        self.assertEqual(student.enrollment_status, Student.EnrollmentStatus.PRE_REGISTERED)
        self.assertEqual(student.unique_id, "3_2222")
        self.assertEqual(student.grade, "고3")
        self.assertEqual(student.school, "한종철고")
        self.assertIsNone(student.credentials_sent_at)  # 발송은 알림톡 연동 대기

        parent = Parent.objects.get(phone="01033334444")
        self.assertIsNotNone(parent.user)
        self.assertEqual(parent.user.role, User.Role.PARENT)
        self.assertEqual(parent.user.login_id, "01033334444")
        self.assertIsNone(parent.credentials_sent_at)
        self.assertTrue(result["parent"]["created"])
        self.assertTrue(parent.user.check_password(result["parent"]["initial_password"]))
        self.assertTrue(
            ParentStudent.objects.filter(parent=parent, student=student).exists()
        )

    def test_duplicate_parent_phone_links_to_existing_parent(self):
        rows = [
            {"name": "김첫째", "phone": "01011110001", "parent_phone": "01099998888"},
            {"name": "김둘째", "phone": "01011110002", "parent_phone": "01099998888"},
        ]
        res = self.post_bulk(rows)
        body = res.json()
        self.assertEqual(Parent.objects.filter(phone="01099998888").count(), 1)
        parent = Parent.objects.get(phone="01099998888")
        self.assertEqual(ParentStudent.objects.filter(parent=parent).count(), 2)
        self.assertTrue(body["results"][0]["parent"]["created"])
        self.assertFalse(body["results"][1]["parent"]["created"])
        self.assertNotIn("initial_password", body["results"][1]["parent"])

    def test_existing_parent_in_db_gets_link_only(self):
        existing = Parent.objects.create(
            user=make_user("01055550000", User.Role.PARENT, name="기존학부모"),
            phone="01055550000",
        )
        res = self.post_bulk(
            [{"name": "신규생", "phone": "01055551111", "parent_phone": "01055550000"}]
        )
        body = res.json()
        self.assertFalse(body["results"][0]["parent"]["created"])
        self.assertEqual(Parent.objects.filter(phone="01055550000").count(), 1)
        student = Student.objects.get(user__login_id="01055551111")
        self.assertTrue(
            ParentStudent.objects.filter(parent=existing, student=student).exists()
        )

    def test_phoneless_student_uses_parent_phone_with_suffix(self):
        rows = [
            {"name": "무폰첫째", "parent_phone": "01077770000"},
            {"name": "무폰둘째", "parent_phone": "01077770000"},
        ]
        res = self.post_bulk(rows)
        body = res.json()
        self.assertEqual(body["results"][0]["login_id"], "01077770000a")
        self.assertEqual(body["results"][1]["login_id"], "01077770000b")
        self.assertTrue(User.objects.filter(login_id="01077770000a").exists())
        self.assertTrue(User.objects.filter(login_id="01077770000b").exists())
        # 학부모 본인 아이디는 접미사 없는 원번호.
        self.assertTrue(
            User.objects.filter(login_id="01077770000", role=User.Role.PARENT).exists()
        )

    def test_duplicate_login_id_fails_only_that_row(self):
        make_user("01088880000", User.Role.STUDENT, name="선점자")
        rows = [
            {"name": "중복생", "phone": "01088880000"},
            {"name": "정상생", "phone": "01088880001"},
        ]
        res = self.post_bulk(rows)
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["results"][0]["status"], "실패")
        self.assertTrue(body["results"][0]["error"])
        self.assertEqual(body["results"][1]["status"], "생성")
        # 실패 행 잔재 없음(행 단위 savepoint 롤백) — 성공 행은 유지.
        self.assertFalse(Student.objects.filter(user__login_id="01088880000").exists())
        self.assertTrue(Student.objects.filter(user__login_id="01088880001").exists())
        self.assertEqual(body["summary"]["created"], 1)
        self.assertEqual(body["summary"]["failed"], 1)

    def test_row_without_any_phone_fails_that_row(self):
        res = self.post_bulk([{"name": "무연락생"}])
        body = res.json()
        self.assertEqual(body["results"][0]["status"], "실패")

    def test_row_without_name_fails_that_row(self):
        res = self.post_bulk([{"phone": "01012340000"}])
        body = res.json()
        self.assertEqual(body["results"][0]["status"], "실패")
        self.assertFalse(User.objects.filter(login_id="01012340000").exists())

    def test_non_list_or_empty_body_rejected(self):
        self.assertEqual(self.post_bulk({"name": "딕셔너리"}).status_code, 400)
        self.assertEqual(self.post_bulk([]).status_code, 400)


class RegisterTests(ProvisioningFixtureMixin, TestCase):
    """POST /api/admin/accounts/{student_id}/register — 예비등록→등록."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.student = Student.objects.create(
            user=make_user("rg-stu", User.Role.STUDENT, name="예비생"),
            unique_id="3_0001",
        )

    def register(self, student_id, user=None):
        self.client.force_login(user or self.admin)
        return self.client.post(f"/api/admin/accounts/{student_id}/register")

    def test_registers_pre_registered_student(self):
        res = self.register(self.student.student_id)
        self.assertEqual(res.status_code, 200)
        self.student.refresh_from_db()
        self.assertEqual(self.student.enrollment_status, Student.EnrollmentStatus.REGISTERED)
        self.assertIsNotNone(self.student.registered_at)
        self.assertEqual(res.json()["enrollment_status"], "등록")

    def test_already_registered_rejected(self):
        self.register(self.student.student_id)
        self.assertEqual(self.register(self.student.student_id).status_code, 400)

    def test_withdrawn_rejected(self):
        self.student.enrollment_status = Student.EnrollmentStatus.WITHDRAWN
        self.student.save(update_fields=["enrollment_status"])
        self.assertEqual(self.register(self.student.student_id).status_code, 400)

    def test_unknown_student_404(self):
        self.assertEqual(self.register(999999).status_code, 404)

    def test_assistant_without_feature_gets_403(self):
        self.assertEqual(
            self.register(self.student.student_id, user=self.assistant).status_code, 403
        )

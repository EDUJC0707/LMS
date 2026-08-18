"""accounts API 1차 슬라이스 테스트 — 권한 부품·인증 3종·/me (PRD §4).

- 권한 부품(IsStudent/IsParent/IsStaffRole/FeatureRequired)은 프로브 뷰
  (APIRequestFactory)로 단위 검증한다 — 검증 대상은 퍼미션 클래스이고
  뷰는 하네스일 뿐이다.
- 인증·/me 는 실제 URL 라우팅을 통해 통합 검증한다(세션 수립 포함).
"""
from django.test import TestCase
from rest_framework.response import Response
from rest_framework.test import APIClient, APIRequestFactory, force_authenticate
from rest_framework.views import APIView

from apps.curriculum.models import Class, Course, CourseEnrollment

from .features import ROLE_PRESETS, FeatureKey
from .models import Parent, ParentStudent, StaffFeatureGrant, Student, User
from .permissions import FeatureRequired, IsParent, IsStaffRole, IsStudent

PASSWORD = "pw-Secret-77!"


def make_user(login_id, role, name="사용자", password=PASSWORD, **extra):
    return User.objects.create_user(
        login_id=login_id, password=password, name=name, role=role, **extra
    )


def probe_status(permission_class, user=None):
    """퍼미션 클래스 하나를 단 프로브 뷰에 GET 을 날려 상태코드를 돌려준다."""

    class _Probe(APIView):
        permission_classes = [permission_class]

        def get(self, request):
            return Response({"ok": True})

    request = APIRequestFactory().get("/probe")
    if user is not None:
        force_authenticate(request, user=user)
    return _Probe.as_view()(request).status_code


class RolePermissionTests(TestCase):
    """IsStudent / IsParent / IsStaffRole — 역할군 게이트."""

    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user("perm-own", User.Role.OWNER)
        cls.admin = make_user("perm-adm", User.Role.ADMIN)
        cls.assistant = make_user("perm-ast", User.Role.ASSISTANT)
        cls.student = make_user("perm-stu", User.Role.STUDENT)
        cls.parent = make_user("perm-par", User.Role.PARENT)

    def test_is_student_allows_student_only(self):
        self.assertEqual(probe_status(IsStudent, self.student), 200)
        self.assertEqual(probe_status(IsStudent, self.parent), 403)
        self.assertEqual(probe_status(IsStudent, self.admin), 403)
        self.assertEqual(probe_status(IsStudent, self.owner), 403)

    def test_is_parent_allows_parent_only(self):
        self.assertEqual(probe_status(IsParent, self.parent), 200)
        self.assertEqual(probe_status(IsParent, self.student), 403)
        self.assertEqual(probe_status(IsParent, self.assistant), 403)

    def test_is_staff_role_allows_owner_admin_assistant(self):
        self.assertEqual(probe_status(IsStaffRole, self.owner), 200)
        self.assertEqual(probe_status(IsStaffRole, self.admin), 200)
        self.assertEqual(probe_status(IsStaffRole, self.assistant), 200)
        self.assertEqual(probe_status(IsStaffRole, self.student), 403)
        self.assertEqual(probe_status(IsStaffRole, self.parent), 403)

    def test_anonymous_denied_everywhere(self):
        self.assertEqual(probe_status(IsStudent), 403)
        self.assertEqual(probe_status(IsParent), 403)
        self.assertEqual(probe_status(IsStaffRole), 403)


class FeatureRequiredTests(TestCase):
    """FeatureRequired(feature_key) — effective_features(프리셋 ⊕ delta) 강제."""

    def test_admin_preset_feature_allowed(self):
        admin = make_user("ft-adm1", User.Role.ADMIN)
        self.assertEqual(probe_status(FeatureRequired(FeatureKey.GRADE_PROCESSING), admin), 200)

    def test_admin_without_feature_denied(self):
        # 권한부여는 관리자 프리셋에 없다(대표 전용 후보) — 기본 차단
        admin = make_user("ft-adm2", User.Role.ADMIN)
        self.assertEqual(probe_status(FeatureRequired(FeatureKey.FEATURE_GRANT_ADMIN), admin), 403)

    def test_delta_grant_opens_feature(self):
        # 조교 프리셋 밖 기능을 delta(is_granted=true)로 부여 → 허용
        assistant = make_user("ft-ast1", User.Role.ASSISTANT)
        StaffFeatureGrant.objects.create(
            user=assistant, feature_key=FeatureKey.ATTENDANCE_ENTRY, is_granted=True
        )
        self.assertEqual(probe_status(FeatureRequired(FeatureKey.ATTENDANCE_ENTRY), assistant), 200)

    def test_delta_revoke_closes_preset_feature(self):
        # 관리자 프리셋 기능을 delta(is_granted=false)로 회수 → 차단
        admin = make_user("ft-adm3", User.Role.ADMIN)
        StaffFeatureGrant.objects.create(
            user=admin, feature_key=FeatureKey.GRADE_PROCESSING, is_granted=False
        )
        self.assertEqual(probe_status(FeatureRequired(FeatureKey.GRADE_PROCESSING), admin), 403)

    def test_owner_short_circuits_everything(self):
        # 대표 전권 단락 — 회수 delta 가 있어도 무시
        owner = make_user("ft-own1", User.Role.OWNER)
        StaffFeatureGrant.objects.create(
            user=owner, feature_key=FeatureKey.FEATURE_GRANT_ADMIN, is_granted=False
        )
        self.assertEqual(probe_status(FeatureRequired(FeatureKey.FEATURE_GRANT_ADMIN), owner), 200)

    def test_consumer_roles_always_denied(self):
        # 학생·학부모는 직원 기능 없음 — 닫힘이 기본값(key_considerations §5)
        student = make_user("ft-stu1", User.Role.STUDENT)
        self.assertEqual(probe_status(FeatureRequired(FeatureKey.WORKBOOK_UPLOAD), student), 403)

    def test_anonymous_denied(self):
        self.assertEqual(probe_status(FeatureRequired(FeatureKey.GRADE_PROCESSING)), 403)


class LoginTests(TestCase):
    """로그인 진입점 2종(2026-07-28 개편) — 소비자 통합 + 직원 분리(PRD §4).

    - `POST /api/auth/login` 학생·학부모 공용. 역할은 **DB 의 user.role** 로
      판정하고 응답에 실어 프런트가 홈을 고른다.
    - `POST /api/auth/login/admin` 직원(대표·관리자·조교) 전용, 화면 미노출.
    """

    def setUp(self):
        self.client = APIClient()

    def login(self, login_id, password=PASSWORD):
        return self.client.post(
            "/api/auth/login",
            {"login_id": login_id, "password": password},
            format="json",
        )

    def login_admin(self, login_id, password=PASSWORD):
        return self.client.post(
            "/api/auth/login/admin",
            {"login_id": login_id, "password": password},
            format="json",
        )

    def test_student_login_success_establishes_session(self):
        user = make_user("김학생1234", User.Role.STUDENT, name="김학생")
        resp = self.login("김학생1234")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["user_id"], user.user_id)
        self.assertEqual(data["name"], "김학생")
        self.assertEqual(data["role"], "학생")
        self.assertTrue(data["must_change_password"])  # 일괄생성 기본값
        self.assertIn("_auth_user_id", self.client.session)  # 세션 로그인 수립

    def test_parent_login_uses_same_endpoint(self):
        make_user("김학생1234p", User.Role.PARENT, name="김학생 학부모")
        resp = self.login("김학생1234p")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["role"], "학부모")
        self.assertIn("_auth_user_id", self.client.session)

    def test_role_comes_from_db_not_id_suffix(self):
        # 아이디 규칙은 언제든 바뀐다 — p 접미사가 아니라 users.role 이 준거.
        make_user("이상한p", User.Role.STUDENT)  # p 로 끝나는 학생 계정
        make_user("접미사없는학부모", User.Role.PARENT)
        self.assertEqual(self.login("이상한p").json()["role"], "학생")
        self.assertEqual(APIClient().post(
            "/api/auth/login",
            {"login_id": "접미사없는학부모", "password": PASSWORD},
            format="json",
        ).json()["role"], "학부모")

    def test_login_response_excludes_phone(self):
        # 개인정보 최소 원칙 — 연락처는 응답에 싣지 않는다
        make_user("lg-stu2", User.Role.STUDENT, phone="010-1111-2222")
        resp = self.login("lg-stu2")
        self.assertNotIn("phone", resp.json())

    def test_wrong_password_401(self):
        make_user("lg-stu3", User.Role.STUDENT)
        resp = self.login("lg-stu3", password="wrong-pass-1!")
        self.assertEqual(resp.status_code, 401)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_unknown_login_id_401(self):
        self.assertEqual(self.login("no-such-user").status_code, 401)

    def test_inactive_user_blocked_401(self):
        make_user("lg-stu4", User.Role.STUDENT, is_active=False)
        self.assertEqual(self.login("lg-stu4").status_code, 401)

    def test_staff_rejected_on_consumer_endpoint_with_same_message(self):
        # 직원이 소비자 경로로 — 403 이되 메시지는 401 과 동일(존재 노출 최소화)
        make_user("lg-adm2", User.Role.ADMIN)
        mismatch = self.login("lg-adm2")
        self.assertEqual(mismatch.status_code, 403)
        self.assertNotIn("_auth_user_id", self.client.session)
        bad_cred = self.login("lg-adm2", password="wrong-pass-1!")
        self.assertEqual(mismatch.json()["detail"], bad_cred.json()["detail"])

    def test_admin_endpoint_accepts_all_staff_roles(self):
        make_user("lg-own1", User.Role.OWNER)
        make_user("lg-adm1", User.Role.ADMIN)
        make_user("lg-ast1", User.Role.ASSISTANT)
        for login_id in ("lg-own1", "lg-adm1", "lg-ast1"):
            self.assertEqual(APIClient().post(
                "/api/auth/login/admin",
                {"login_id": login_id, "password": PASSWORD},
                format="json",
            ).status_code, 200)

    def test_admin_endpoint_rejects_consumers(self):
        make_user("lg-stu5", User.Role.STUDENT)
        make_user("lg-par1", User.Role.PARENT)
        self.assertEqual(self.login_admin("lg-stu5").status_code, 403)
        self.assertEqual(self.login_admin("lg-par1").status_code, 403)

    def test_role_split_login_paths_removed(self):
        # 학생·학부모 분리 경로는 제거됨(통합 엔드포인트로 대체 — 호환 유지 없음)
        for path in ("/api/auth/login/student", "/api/auth/login/parent"):
            resp = self.client.post(
                path, {"login_id": "lg-x", "password": PASSWORD}, format="json"
            )
            self.assertEqual(resp.status_code, 404, path)

    def test_missing_fields_400(self):
        resp = self.client.post("/api/auth/login", {"login_id": "x"}, format="json")
        self.assertEqual(resp.status_code, 400)


class LogoutTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_logout_clears_session(self):
        make_user("lo-stu1", User.Role.STUDENT)
        self.client.post(
            "/api/auth/login",
            {"login_id": "lo-stu1", "password": PASSWORD},
            format="json",
        )
        self.assertIn("_auth_user_id", self.client.session)
        resp = self.client.post("/api/auth/logout")
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_logout_is_idempotent_for_anonymous(self):
        self.assertEqual(self.client.post("/api/auth/logout").status_code, 200)


class PasswordChangeTests(TestCase):
    NEW_PASSWORD = "cH4nged-pw-2026!"

    def setUp(self):
        self.client = APIClient()
        self.user = make_user("pw-stu1", User.Role.STUDENT)
        self.client.post(
            "/api/auth/login",
            {"login_id": "pw-stu1", "password": PASSWORD},
            format="json",
        )

    def change(self, current, new):
        return self.client.post(
            "/api/auth/password",
            {"current_password": current, "new_password": new},
            format="json",
        )

    def test_change_success_flips_flag_and_stamps_time(self):
        self.assertTrue(self.user.must_change_password)
        resp = self.change(PASSWORD, self.NEW_PASSWORD)
        self.assertEqual(resp.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.NEW_PASSWORD))
        self.assertFalse(self.user.must_change_password)  # 최초 변경 강제 해제
        self.assertIsNotNone(self.user.password_changed_at)
        # 세션 유지(update_session_auth_hash) — 변경 직후 재로그인 강요 없음
        self.assertIn("_auth_user_id", self.client.session)

    def test_relogin_with_new_password(self):
        self.change(PASSWORD, self.NEW_PASSWORD)
        fresh = APIClient()
        resp = fresh.post(
            "/api/auth/login",
            {"login_id": "pw-stu1", "password": self.NEW_PASSWORD},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["must_change_password"])

    def test_wrong_current_password_400(self):
        resp = self.change("wrong-pass-1!", self.NEW_PASSWORD)
        self.assertEqual(resp.status_code, 400)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(PASSWORD))  # 변경되지 않음

    def test_weak_new_password_400(self):
        # AUTH_PASSWORD_VALIDATORS(최소 길이·숫자만 금지 등) 적용
        resp = self.change(PASSWORD, "1234")
        self.assertEqual(resp.status_code, 400)

    def test_requires_authentication(self):
        resp = APIClient().post(
            "/api/auth/password",
            {"current_password": PASSWORD, "new_password": self.NEW_PASSWORD},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)  # SessionAuth 미인증 → 403


class CsrfEndpointTests(TestCase):
    def test_csrf_endpoint_sets_cookie(self):
        resp = APIClient().get("/api/auth/csrf")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("csrftoken", resp.cookies)  # Django 기본 쿠키명 유지


class MeTestBase(TestCase):
    """공통: 로그인 후 GET /api/me — 소비자는 통합 경로, 직원만 별도 경로."""

    CONSUMER_ROLES = {User.Role.STUDENT, User.Role.PARENT}

    def me_as(self, user):
        client = APIClient()
        path = "/api/auth/login" if user.role in self.CONSUMER_ROLES else "/api/auth/login/admin"
        login = client.post(
            path,
            {"login_id": user.login_id, "password": PASSWORD},
            format="json",
        )
        assert login.status_code == 200, login.content
        return client.get("/api/me")


class MeCommonTests(MeTestBase):
    def test_requires_authentication(self):
        self.assertEqual(APIClient().get("/api/me").status_code, 403)

    def test_common_fields_and_no_phone(self):
        user = make_user("me-stu0", User.Role.STUDENT, name="김학생", phone="010-1111-2222")
        Student.objects.create(user=user, matching_key="2-1111")
        data = self.me_as(user).json()
        self.assertEqual(data["user_id"], user.user_id)
        self.assertEqual(data["name"], "김학생")
        self.assertEqual(data["role"], "학생")
        self.assertTrue(data["must_change_password"])
        # 개인정보 최소 원칙 — 응답 어디에도 연락처가 없어야 한다
        self.assertNotIn("010-1111-2222", self.me_as(user).content.decode())


class MeStudentTests(MeTestBase):
    def test_registered_student_payload(self):
        user = make_user("me-stu1", User.Role.STUDENT, name="김등록")
        student = Student.objects.create(
            user=user,
            matching_key="2-1234",
            grade="고2",
            enrollment_status=Student.EnrollmentStatus.REGISTERED,
        )
        # 반 이름은 수강이 가리키는 반에서 온다(사본 없음)
        course = Course.objects.create(name="로직엔제")
        CourseEnrollment.objects.create(
            student=student,
            course=course,
            klass=Class.objects.create(course=course, name="일요 3반"),
        )
        data = self.me_as(user).json()
        self.assertEqual(
            data["student"],
            {
                "student_id": student.student_id,
                "enrollment_status": "등록",
                "grade": "고2",
                "current_class": "일요 3반",
            },
        )
        # 역할 밖 블록은 내려가지 않는다(상태 기반 노출)
        self.assertNotIn("children", data)
        self.assertNotIn("features", data)

    def test_pre_registered_student_exposed_for_bare_render(self):
        # 미등록(예비등록) — 프런트는 이 값으로 bare 렌더(교재 구매만) 판단
        user = make_user("me-stu2", User.Role.STUDENT)
        Student.objects.create(user=user, matching_key="2-2222")
        data = self.me_as(user).json()
        self.assertEqual(data["student"]["enrollment_status"], "예비등록")

    def test_student_without_row_gets_null(self):
        # 계정만 있고 students 행이 없는 예외 상태 — null 로 방어(500 금지)
        user = make_user("me-stu3", User.Role.STUDENT)
        data = self.me_as(user).json()
        self.assertIsNone(data["student"])


class MeParentTests(MeTestBase):
    def test_children_list_for_dropdown(self):
        user = make_user("me-par1", User.Role.PARENT, name="박학부모")
        parent = Parent.objects.create(user=user, phone="010-9999-8888")
        child1_user = make_user("me-kid1", User.Role.STUDENT, name="김첫째")
        child1 = Student.objects.create(
            user=child1_user,
            matching_key="1-1111",
            grade="고1",
            enrollment_status=Student.EnrollmentStatus.REGISTERED,
        )
        child2 = Student.objects.create(matching_key="3-3333", grade="고3")  # 계정 미발급 자녀
        ParentStudent.objects.create(parent=parent, student=child1, relation="모")
        ParentStudent.objects.create(parent=parent, student=child2, relation="모")
        data = self.me_as(user).json()
        self.assertEqual(
            data["children"],
            [
                {
                    "student_id": child1.student_id,
                    "name": "김첫째",
                    "grade": "고1",
                    "enrollment_status": "등록",
                },
                {
                    "student_id": child2.student_id,
                    "name": None,
                    "grade": "고3",
                    "enrollment_status": "예비등록",
                },
            ],
        )
        self.assertNotIn("student", data)
        self.assertNotIn("features", data)

    def test_children_enrollment_status_drives_menu_assembly(self):
        # 예비등록 자녀만 둔 학부모 — 프런트가 성적·워크북 메뉴를 접을 근거
        user = make_user("me-par3", User.Role.PARENT, name="박예비")
        parent = Parent.objects.create(user=user, phone="010-7777-6666")
        pre = Student.objects.create(matching_key="1-9999", grade="고1")
        withdrawn = Student.objects.create(
            matching_key="1-8888",
            grade="고1",
            enrollment_status=Student.EnrollmentStatus.WITHDRAWN,
        )
        ParentStudent.objects.create(parent=parent, student=pre)
        ParentStudent.objects.create(parent=parent, student=withdrawn)
        statuses = [c["enrollment_status"] for c in self.me_as(user).json()["children"]]
        self.assertEqual(statuses, ["예비등록", "퇴원"])

    def test_parent_without_row_gets_empty_children(self):
        user = make_user("me-par2", User.Role.PARENT)
        data = self.me_as(user).json()
        self.assertEqual(data["children"], [])


class MeStaffTests(MeTestBase):
    def test_admin_features_match_preset(self):
        user = make_user("me-adm1", User.Role.ADMIN)
        data = self.me_as(user).json()
        self.assertEqual(set(data["features"]), set(ROLE_PRESETS[User.Role.ADMIN]))
        self.assertEqual(data["features"], sorted(data["features"]))  # 결정적 순서
        self.assertNotIn("student", data)
        self.assertNotIn("children", data)

    def test_assistant_features_reflect_delta(self):
        # delta 가감(부여+회수)이 /me 메뉴 계약에 그대로 반영된다
        user = make_user("me-ast1", User.Role.ASSISTANT)
        StaffFeatureGrant.objects.create(
            user=user, feature_key=FeatureKey.ATTENDANCE_ENTRY, is_granted=True
        )
        StaffFeatureGrant.objects.create(
            user=user, feature_key=FeatureKey.WORKBOOK_UPLOAD, is_granted=False
        )
        features = set(self.me_as(user).json()["features"])
        self.assertIn(FeatureKey.ATTENDANCE_ENTRY, features)
        self.assertNotIn(FeatureKey.WORKBOOK_UPLOAD, features)
        self.assertIn(FeatureKey.CLINIC_ASSIGN, features)  # 프리셋 잔여분 유지

    def test_owner_has_every_feature(self):
        user = make_user("me-own1", User.Role.OWNER)
        data = self.me_as(user).json()
        self.assertEqual(set(data["features"]), {key.value for key in FeatureKey})


class DevSettingsContractTests(TestCase):
    def test_default_permission_stays_authenticated(self):
        # 과거 감사 지적: dev 가 AllowAny 로 전역 오버라이드 — 진짜 인증이 생겼으므로 금지
        from django.conf import settings

        self.assertEqual(
            settings.REST_FRAMEWORK["DEFAULT_PERMISSION_CLASSES"],
            ["rest_framework.permissions.IsAuthenticated"],
        )

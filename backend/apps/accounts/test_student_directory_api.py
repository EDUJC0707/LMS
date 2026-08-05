"""학생 명부 API 테스트 — GET /api/admin/students (갭 보강, PRD 3.1.5·3.1.7).

검증 축:
- 권한: **직원 공통(IsStaffRole)** — 워크북업로드만 가진 조교도, 계정관리
  관리자도 통과한다(기능 키 하나로 묶으면 한쪽이 막힌다는 판단 —
  student_directory 모듈 docstring). 학생·학부모·비로그인은 403.
- 검색 q: 이름·원번·전화 부분일치(전화는 **검색 키일 뿐 응답 미노출**)
- 필터: enrollment_status(값집합 밖 400)·course_id(비정수 400)·class_name
- 개인정보 최소: 응답 본문에 연락처가 없다
- 페이지네이션: 전역 PAGE_SIZE(20) — 게시판 목록 선례
- 쿼리 효율: assertNumQueries 고정(N+1 회귀 방지)
"""
from django.test import TestCase

from apps.curriculum.models import Course, CourseEnrollment

from .features import FeatureKey
from .models import Parent, StaffFeatureGrant, Student, User

PASSWORD = "pw-Secret-77!"
STUDENTS_URL = "/api/admin/students"


def make_user(login_id, role, name="사용자", **extra):
    return User.objects.create_user(
        login_id=login_id, password=PASSWORD, name=name, role=role, **extra
    )


def make_student(login_id, name, phone="", **extra):
    user = make_user(login_id, User.Role.STUDENT, name=name, phone=phone)
    return Student.objects.create(user=user, **extra)


class StudentDirectoryFixtureMixin:
    """학생 5명(등록 3·예비등록 1·퇴원 1) + 강좌 2개."""

    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user("dir-own", User.Role.OWNER, name="대표")
        cls.admin = make_user("dir-adm", User.Role.ADMIN, name="관리자")
        cls.assistant = make_user("dir-ast", User.Role.ASSISTANT, name="조교")
        cls.parent_user = make_user("dir-par", User.Role.PARENT, name="학부모")
        Parent.objects.create(user=cls.parent_user, phone="01099998888")

        cls.course = Course.objects.create(name="로직엔제")
        cls.other_course = Course.objects.create(name="파이널")

        cls.s_reg1 = make_student(
            "dir-s1",
            "김서연",
            phone="01011112222",
            matching_key="L2601",
            grade="고2",
            current_class="고2 로직엔제 B반",
            enrollment_status=Student.EnrollmentStatus.REGISTERED,
        )
        cls.s_reg2 = make_student(
            "dir-s2",
            "이준호",
            phone="01033334444",
            matching_key="L2602",
            grade="고2",
            current_class="고2 로직엔제 A반",
            enrollment_status=Student.EnrollmentStatus.REGISTERED,
        )
        cls.s_reg3 = make_student(
            "dir-s3",
            "박민지",
            matching_key="F2603",
            grade="고3",
            current_class="고3 파이널",
            enrollment_status=Student.EnrollmentStatus.REGISTERED,
        )
        cls.s_pre = make_student(
            "dir-s4",
            "정예비",
            matching_key="L2604",
            grade="고1",
            enrollment_status=Student.EnrollmentStatus.PRE_REGISTERED,
        )
        cls.s_out = make_student(
            "dir-s5",
            "최퇴원",
            matching_key="L2605",
            grade="고2",
            enrollment_status=Student.EnrollmentStatus.WITHDRAWN,
        )
        CourseEnrollment.objects.create(student=cls.s_reg1, course=cls.course)
        CourseEnrollment.objects.create(student=cls.s_reg2, course=cls.course)
        CourseEnrollment.objects.create(student=cls.s_reg3, course=cls.other_course)
        # 중단된 수강 — course_id 필터에서 제외되어야 한다
        CourseEnrollment.objects.create(
            student=cls.s_pre,
            course=cls.course,
            status=CourseEnrollment.Status.SUSPENDED,
        )

    def get_directory(self, params=None):
        return self.client.get(STUDENTS_URL, params or {})

    def ids(self, params=None):
        return [row["student_id"] for row in self.get_directory(params).json()["results"]]


class StudentDirectoryAccessTests(StudentDirectoryFixtureMixin, TestCase):
    """직원 공통 게이트 — 조교·관리자·대표 통과, 소비자 역할 차단."""

    def test_anonymous_denied(self):
        self.assertEqual(self.get_directory().status_code, 403)

    def test_student_and_parent_denied(self):
        for user in (self.s_reg1.user, self.parent_user):
            self.client.force_login(user)
            self.assertEqual(self.get_directory().status_code, 403)

    def test_assistant_allowed_without_account_admin_feature(self):
        # 조교 프리셋에는 계정관리가 없다 — 워크북 업로드 대상 선택 동선 보장
        self.client.force_login(self.assistant)
        self.assertEqual(self.get_directory().status_code, 200)

    def test_admin_and_owner_allowed(self):
        for user in (self.admin, self.owner):
            self.client.force_login(user)
            self.assertEqual(self.get_directory().status_code, 200)

    def test_assistant_stripped_of_every_feature_still_allowed(self):
        # 기능 키 축과 무관한 역할 게이트임을 고정(FeatureRequired 로 회귀 방지)
        for key in (FeatureKey.WORKBOOK_UPLOAD, FeatureKey.CLINIC_ASSIGN):
            StaffFeatureGrant.objects.create(
                user=self.assistant, feature_key=key, is_granted=False
            )
        self.client.force_login(self.assistant)
        self.assertEqual(self.get_directory().status_code, 200)

    def test_post_not_allowed(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(STUDENTS_URL).status_code, 405)


class StudentDirectoryPayloadTests(StudentDirectoryFixtureMixin, TestCase):
    """행 형태 — 최소 노출(연락처 없음) + 원번 오름차순 결정적 정렬."""

    def setUp(self):
        self.client.force_login(self.admin)

    def test_row_fields_are_minimal(self):
        rows = {r["student_id"]: r for r in self.get_directory().json()["results"]}
        self.assertEqual(
            rows[self.s_reg1.student_id],
            {
                "student_id": self.s_reg1.student_id,
                "name": "김서연",
                "login_id": self.s_reg1.user.login_id,
                "matching_key": "L2601",
                "grade": "고2",
                "current_class": "고2 로직엔제 B반",
                "enrollment_status": "등록",
            },
        )

    def test_response_carries_no_phone_number(self):
        body = self.get_directory().content.decode()
        self.assertNotIn("01011112222", body)
        self.assertNotIn("phone", body)

    def test_student_without_account_has_null_name(self):
        orphan = Student.objects.create(matching_key="L2699", grade="고1")
        rows = {r["student_id"]: r for r in self.get_directory().json()["results"]}
        self.assertIsNone(rows[orphan.student_id]["name"])

    def test_lists_every_enrollment_status_by_default(self):
        # 닫힘 기본값은 권한 축의 원칙 — 명부는 퇴원·예비등록까지 보여야
        # '등록 전환' 대상과 이력 조회가 가능하다(필터로 좁힌다)
        self.assertEqual(
            set(self.ids()),
            {
                self.s_reg1.student_id,
                self.s_reg2.student_id,
                self.s_reg3.student_id,
                self.s_pre.student_id,
                self.s_out.student_id,
            },
        )

    def test_ordered_by_student_id(self):
        self.assertEqual(self.ids(), sorted(self.ids()))


class StudentDirectorySearchTests(StudentDirectoryFixtureMixin, TestCase):
    """q — 이름·원번·전화 부분일치(OR)."""

    def setUp(self):
        self.client.force_login(self.assistant)

    def test_search_by_partial_name(self):
        self.assertEqual(self.ids({"q": "서연"}), [self.s_reg1.student_id])

    def test_search_by_partial_matching_key(self):
        ids = set(self.ids({"q": "L260"}))
        self.assertIn(self.s_reg1.student_id, ids)
        self.assertNotIn(self.s_reg3.student_id, ids)  # F2603

    def test_search_by_partial_phone(self):
        # 전화는 검색 키로만 쓴다(응답엔 없음) — 학부모 문의 응대 동선
        self.assertEqual(self.ids({"q": "3333"}), [self.s_reg2.student_id])

    def test_search_is_case_insensitive(self):
        self.assertIn(self.s_reg1.student_id, self.ids({"q": "l2601"}))

    def test_blank_query_is_ignored(self):
        self.assertEqual(len(self.ids({"q": "   "})), 5)

    def test_no_match_returns_empty(self):
        body = self.get_directory({"q": "존재하지않는이름"}).json()
        self.assertEqual(body["results"], [])
        self.assertEqual(body["count"], 0)


class StudentDirectoryFilterTests(StudentDirectoryFixtureMixin, TestCase):
    """enrollment_status·course_id·class_name 필터."""

    def setUp(self):
        self.client.force_login(self.admin)

    def test_filter_by_enrollment_status(self):
        self.assertEqual(
            self.ids({"enrollment_status": "예비등록"}), [self.s_pre.student_id]
        )

    def test_invalid_enrollment_status_is_400(self):
        res = self.get_directory({"enrollment_status": "휴원"})
        self.assertEqual(res.status_code, 400)

    def test_filter_by_course_id_uses_active_enrollment_only(self):
        # 중단 수강(s_pre)은 제외 — 활성 수강(`수강`)만 그 강좌의 명부다
        self.assertEqual(
            self.ids({"course_id": self.course.course_id}),
            [self.s_reg1.student_id, self.s_reg2.student_id],
        )

    def test_invalid_course_id_is_400(self):
        self.assertEqual(self.get_directory({"course_id": "abc"}).status_code, 400)

    def test_unknown_course_id_returns_empty(self):
        self.assertEqual(self.ids({"course_id": 999999}), [])

    def test_filter_by_class_name(self):
        self.assertEqual(self.ids({"class_name": "B반"}), [self.s_reg1.student_id])

    def test_filters_combine_with_search(self):
        ids = self.ids(
            {"q": "L260", "enrollment_status": "등록", "course_id": self.course.course_id}
        )
        self.assertEqual(ids, [self.s_reg1.student_id, self.s_reg2.student_id])


class StudentDirectoryPaginationTests(StudentDirectoryFixtureMixin, TestCase):
    """페이지네이션 — 전역 PAGE_SIZE(20), count/next 계약(게시판 선례)."""

    def setUp(self):
        self.client.force_login(self.admin)

    def test_page_size_and_next_link(self):
        for index in range(20):
            make_student(f"dir-bulk{index}", f"대량{index}", matching_key=f"B26{index:02d}")
        body = self.get_directory().json()
        self.assertEqual(body["count"], 25)
        self.assertEqual(len(body["results"]), 20)
        self.assertIsNotNone(body["next"])
        self.assertIsNone(body["previous"])
        page2 = self.get_directory({"page": 2}).json()
        self.assertEqual(len(page2["results"]), 5)


class StudentDirectoryQueryCountTests(StudentDirectoryFixtureMixin, TestCase):
    """N+1 회귀 방지 — 학생 수와 무관하게 쿼리 수 고정."""

    def setUp(self):
        self.client.force_login(self.admin)

    def test_query_count_is_fixed(self):
        with self.assertNumQueries(4):  # 세션인증 2 + count 1 + 페이지 1
            self.get_directory()

    def test_query_count_does_not_grow_with_rows(self):
        for index in range(10):
            make_student(f"dir-n{index}", f"엔플러스{index}", matching_key=f"N26{index:02d}")
        with self.assertNumQueries(4):
            self.get_directory()

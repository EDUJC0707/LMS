"""반 개설 API 테스트 — GET·POST /api/admin/classes (FLOW 1-2·1-3).

검증 축:
- 기능 게이트: 계정관리 키(FeatureRequired) — 조교 프리셋에 없어 403,
  delta 부여 시 허용. 학생·비로그인은 차단
- 개설: 커리와 반을 한 번에 / 이미 있는 커리에 반만 더하기 / 같은 커리에
  같은 반 이름은 거절
- 회차: 개강일에서 주 단위로 총주차만큼 — 1주차 9/4 · 2주차 9/11 · … ·
  10주차 11/6. 반의 주차가 곧 회차라 `ClassSession(klass, week_no)` 다
- 목록: 커리로 묶고, 반마다 진행 주차와 수강생 수
"""
import datetime
import json

from django.test import TestCase

from apps.accounts.features import FeatureKey
from apps.accounts.models import StaffFeatureGrant, Student, User
from apps.grades.models import ClassSession

from .models import Class, Course, CourseEnrollment, CourseWeek

PASSWORD = "pw-Secret-77!"
URL = "/api/admin/classes"


def make_user(login_id, role, name="사용자"):
    return User.objects.create_user(
        login_id=login_id, password=PASSWORD, name=name, role=role
    )


class ClassAdminFixtureMixin:
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user("cl-own", User.Role.OWNER, name="대표")
        cls.admin = make_user("cl-adm", User.Role.ADMIN, name="관리자")
        cls.assistant = make_user("cl-ast", User.Role.ASSISTANT, name="조교")

    def post_class(self, body, user=None):
        self.client.force_login(user or self.admin)
        return self.client.post(
            URL, data=json.dumps(body), content_type="application/json"
        )

    def get_classes(self, user=None):
        self.client.force_login(user or self.admin)
        return self.client.get(URL)


class ClassAdminGateTests(ClassAdminFixtureMixin, TestCase):
    """계정관리 기능 키 게이트 — 프리셋 ⊕ delta."""

    def test_owner_and_admin_pass(self):
        self.assertEqual(self.get_classes(self.owner).status_code, 200)
        self.assertEqual(self.get_classes(self.admin).status_code, 200)

    def test_assistant_without_feature_gets_403(self):
        self.assertEqual(self.get_classes(self.assistant).status_code, 403)
        self.assertEqual(self.post_class({}, user=self.assistant).status_code, 403)

    def test_assistant_with_delta_passes_gate(self):
        StaffFeatureGrant.objects.create(
            user=self.assistant,
            feature_key=FeatureKey.ACCOUNT_ADMIN,
            is_granted=True,
            granted_by=self.owner,
        )
        self.assertEqual(self.get_classes(self.assistant).status_code, 200)

    def test_student_gets_403(self):
        student = make_user("cl-stu", User.Role.STUDENT)
        self.assertEqual(self.get_classes(student).status_code, 403)

    def test_anonymous_is_blocked(self):
        self.assertIn(self.client.get(URL).status_code, (401, 403))
        self.assertIn(self.client.post(URL, data={}).status_code, (401, 403))


class OpenClassTests(ClassAdminFixtureMixin, TestCase):
    """POST /api/admin/classes — 커리 + 반 + 회차."""

    BODY = {
        "course_name": "2026 여름 N제",
        "total_weeks": 10,
        "name": "목 6.5 대치러셀",
        "start_date": "2026-09-04",
    }

    def test_creates_course_class_and_weekly_sessions(self):
        res = self.post_class(self.BODY)
        self.assertEqual(res.status_code, 201)
        body = res.json()
        self.assertEqual(body["name"], "목 6.5 대치러셀")
        self.assertEqual(body["week_count"], 10)
        self.assertEqual(body["student_count"], 0)

        course = Course.objects.get(name="2026 여름 N제")
        self.assertEqual(course.total_weeks, 10)
        klass = Class.objects.get(pk=body["class_id"])
        self.assertEqual(klass.course_id, course.course_id)
        self.assertEqual(klass.start_date, datetime.date(2026, 9, 4))

        # FLOW 1-3: 개강일에서 주 단위 — 1주차 9/4 · 2주차 9/11 · … · 10주차 11/6
        sessions = list(ClassSession.objects.filter(klass=klass).order_by("week_no"))
        self.assertEqual([s.week_no for s in sessions], list(range(1, 11)))
        self.assertEqual(sessions[0].session_date, datetime.date(2026, 9, 4))
        self.assertEqual(sessions[1].session_date, datetime.date(2026, 9, 11))
        self.assertEqual(sessions[-1].session_date, datetime.date(2026, 11, 6))
        # 커리 주차(내용·영상 자리)가 회차에 물려 있다
        self.assertEqual(CourseWeek.objects.filter(course=course).count(), 10)
        self.assertEqual([s.course_week.week_no for s in sessions], list(range(1, 11)))

    def test_second_class_reuses_the_course_weeks(self):
        first = self.post_class(self.BODY).json()
        res = self.post_class(
            {
                "course_id": first["course_id"],
                "name": "화 6.5 대치러셀",
                "start_date": "2026-09-02",
            }
        )
        self.assertEqual(res.status_code, 201)
        self.assertEqual(Course.objects.count(), 1)
        self.assertEqual(CourseWeek.objects.count(), 10)  # 반마다 만들지 않는다
        self.assertEqual(ClassSession.objects.count(), 20)
        klass = Class.objects.get(pk=res.json()["class_id"])
        self.assertEqual(
            ClassSession.objects.get(klass=klass, week_no=1).session_date,
            datetime.date(2026, 9, 2),
        )

    def test_same_name_in_one_course_is_rejected(self):
        first = self.post_class(self.BODY).json()
        res = self.post_class(
            {
                "course_id": first["course_id"],
                "name": "목 6.5 대치러셀",
                "start_date": "2026-09-04",
            }
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(Class.objects.count(), 1)

    def test_bad_input_is_rejected_without_creating_anything(self):
        for body in (
            {**self.BODY, "name": " "},
            {**self.BODY, "start_date": "2026-13-40"},
            {**self.BODY, "start_date": None},
            {**self.BODY, "course_name": ""},
            {**self.BODY, "total_weeks": 0},
            {**self.BODY, "total_weeks": 53},
            {**self.BODY, "total_weeks": "열"},
            {**self.BODY, "course_id": 999999},
        ):
            with self.subTest(body=body):
                self.assertEqual(self.post_class(body).status_code, 400)
        self.assertEqual(Course.objects.count(), 0)
        self.assertEqual(Class.objects.count(), 0)
        self.assertEqual(ClassSession.objects.count(), 0)


class ClassListTests(ClassAdminFixtureMixin, TestCase):
    """GET /api/admin/classes — 커리로 묶은 목록."""

    def test_groups_classes_under_their_course_with_counts(self):
        course = Course.objects.create(name="2026 여름 N제", total_weeks=10)
        klass = Class.objects.create(
            course=course, name="목 6.5 대치러셀", start_date=datetime.date(2026, 9, 4)
        )
        Class.objects.create(
            course=course, name="화 6.5 대치러셀", start_date=datetime.date(2026, 9, 2)
        )
        today = datetime.date.today()
        for week_no in range(1, 11):
            ClassSession.objects.create(
                klass=klass,
                week_no=week_no,
                session_date=today - datetime.timedelta(weeks=3 - week_no),
            )
        for index in range(2):
            student = Student.objects.create(
                user=make_user(f"cl-s{index}", User.Role.STUDENT, name=f"학생{index}"),
                matching_key=f"학생{index}0001",
            )
            CourseEnrollment.objects.create(student=student, course=course, klass=klass)

        body = self.get_classes().json()
        self.assertEqual(len(body["courses"]), 1)
        group = body["courses"][0]
        self.assertEqual(group["name"], "2026 여름 N제")
        self.assertEqual(group["total_weeks"], 10)
        self.assertEqual(
            [c["name"] for c in group["classes"]], ["목 6.5 대치러셀", "화 6.5 대치러셀"]
        )
        first = group["classes"][0]
        self.assertEqual(first["week_count"], 10)
        self.assertEqual(first["current_week"], 3)  # 오늘까지 지난 회차
        self.assertEqual(first["student_count"], 2)
        self.assertEqual(group["classes"][1]["week_count"], 0)

    def test_empty_when_no_class_exists(self):
        Course.objects.create(name="반 없는 커리", total_weeks=4)
        self.assertEqual(self.get_classes().json(), {"courses": []})

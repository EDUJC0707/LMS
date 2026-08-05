"""내 알림 내역 API 8차 슬라이스 테스트 — 대상 3분기 매칭 (설계 도메인 8).

검증 축:
- 3분기: 학생→student 행 / 학부모→parent 행 / 직원→user 행만 각각 보인다
  (타인·타분기 행 미노출 — 닫힘이 기본값)
- 최신순 + 페이지네이션(PageNumberPagination 20건 — boards 선례)
- 사람 행 미연결(학생 role 인데 students 행 없음) 방어 — 빈 목록
"""
from django.test import TestCase

from apps.accounts.models import Parent, Student, User

from .models import Notification

PASSWORD = "pw-Secret-77!"
URL = "/api/me/notifications"


def make_user(login_id, role, name="사용자", **extra):
    return User.objects.create_user(
        login_id=login_id, password=PASSWORD, name=name, role=role, **extra
    )


def notify(**kwargs):
    return Notification.objects.create(
        channel=Notification.Channel.KAKAO,
        type=Notification.Type.GRADE,
        status=Notification.Status.PENDING,
        **kwargs,
    )


class MeNotificationsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.student_user = make_user("nt-stu", User.Role.STUDENT, name="학생")
        cls.student = Student.objects.create(user=cls.student_user, matching_key="3_0001")
        cls.other_student = Student.objects.create(
            user=make_user("nt-stu2", User.Role.STUDENT, name="타학생"), matching_key="3_0002"
        )
        cls.parent_user = make_user("nt-par", User.Role.PARENT, name="학부모")
        cls.parent = Parent.objects.create(user=cls.parent_user, phone="01011119999")
        cls.staff = make_user("nt-adm", User.Role.ADMIN, name="관리자")

    def test_student_sees_own_rows_only_latest_first(self):
        first = notify(student=self.student, title="첫 알림")
        second = notify(student=self.student, title="둘째 알림")
        notify(student=self.other_student, title="남의 알림")
        notify(parent=self.parent, title="학부모 알림")
        self.client.force_login(self.student_user)
        body = self.client.get(URL).json()
        self.assertEqual(
            [row["notif_id"] for row in body["results"]],
            [second.notif_id, first.notif_id],
        )
        self.assertEqual(body["count"], 2)

    def test_parent_sees_parent_rows(self):
        notify(parent=self.parent, title="결제 안내")
        notify(student=self.student, title="학생 알림")
        self.client.force_login(self.parent_user)
        body = self.client.get(URL).json()
        self.assertEqual(len(body["results"]), 1)
        self.assertEqual(body["results"][0]["title"], "결제 안내")

    def test_staff_sees_user_rows(self):
        notify(user=self.staff, title="직원 공지")
        notify(student=self.student, title="학생 알림")
        self.client.force_login(self.staff)
        body = self.client.get(URL).json()
        self.assertEqual(len(body["results"]), 1)
        self.assertEqual(body["results"][0]["title"], "직원 공지")

    def test_pagination_20_per_page(self):
        for i in range(25):
            notify(student=self.student, title=f"알림{i}")
        self.client.force_login(self.student_user)
        body = self.client.get(URL).json()
        self.assertEqual(len(body["results"]), 20)
        self.assertIsNotNone(body["next"])
        body2 = self.client.get(URL, {"page": 2}).json()
        self.assertEqual(len(body2["results"]), 5)

    def test_student_without_person_row_gets_empty(self):
        orphan = make_user("nt-orphan", User.Role.STUDENT, name="무연결")
        self.client.force_login(orphan)
        body = self.client.get(URL).json()
        self.assertEqual(body["count"], 0)

    def test_anonymous_blocked(self):
        self.assertEqual(self.client.get(URL).status_code, 403)

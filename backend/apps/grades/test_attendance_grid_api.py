"""반별 격자 API 테스트 — 가로 주차 × 세로 학생 (FLOW 3-1 · 5-1).

검증 축:
- 기능 키 게이트: `출결입력`(조교가 여는 화면이다 — `계정관리` 가 아니다)
- 판의 뼈대: 주차는 번호 순 · 칸은 주차와 자리가 맞는다
- 명단: 이 반 수강생 + **이 반에 기록이 있는 학생**(반 이동·현보 — FLOW 3-9)
- `x` 의 재료: 첫 기록 앞의 칸이 비어 있는가 / 기록이 아예 없는 학생은 전부 비었는가
  (`x` 자체는 저장하지도 내려보내지도 않는다 — 화면이 그린다)
- 쿼리 효율: 학생 × 주차라 새는 순간 N+1 이다. 늘려도 같은 수여야 한다
"""
import datetime

from django.test import TestCase

from apps.accounts.features import FeatureKey
from apps.accounts.models import StaffFeatureGrant, Student, User
from apps.curriculum.models import Class, Course, CourseEnrollment

from .models import Attendance, ClassSession

PASSWORD = "pw-Secret-77!"


def grid_url(class_id):
    return f"/api/admin/attendance/classes/{class_id}"


def make_user(login_id, role, name):
    return User.objects.create_user(login_id=login_id, password=PASSWORD, name=name, role=role)


def make_student(login_id, name, status=Student.EnrollmentStatus.REGISTERED):
    user = make_user(login_id, User.Role.STUDENT, name)
    return Student.objects.create(
        user=user, matching_key=f"uid-{login_id}", enrollment_status=status
    )


class AttendanceGridApiTests(TestCase):
    """FLOW 3-1 의 그림 그대로 — 목반 4주차, 학생 넷.

    박지우는 3주차에 들어왔고(앞 두 칸은 기록이 없다), 최현보는 화반 학생인데
    1주차만 이 반에서 들었다(현보 — FLOW 3-4). 한서윤은 퇴원생이다.
    """

    @classmethod
    def setUpTestData(cls):
        cls.admin = make_user("admin-1", User.Role.ADMIN, "관리자")
        cls.assistant = make_user("assist-1", User.Role.ASSISTANT, "조교")

        cls.course = Course.objects.create(name="2026 여름 N제")
        cls.klass = Class.objects.create(course=cls.course, name="목 6.5 대치러셀")
        cls.other = Class.objects.create(course=cls.course, name="화 6.5 대치러셀")
        cls.weeks = [
            ClassSession.objects.create(
                klass=cls.klass,
                week_no=n,
                session_date=datetime.date(2026, 9, 3) + datetime.timedelta(weeks=n - 1),
            )
            for n in (1, 2, 3, 4)
        ]

        cls.haneul = make_student("haneul", "김하늘")
        cls.seojun = make_student("seojun", "이서준")
        cls.jiwoo = make_student("jiwoo", "박지우")
        cls.seoyun = make_student("seoyun", "한서윤", Student.EnrollmentStatus.WITHDRAWN)
        cls.hyunbo = make_student("hyunbo", "최현보")
        for student, klass in (
            (cls.haneul, cls.klass),
            (cls.seojun, cls.klass),
            (cls.jiwoo, cls.klass),
            (cls.seoyun, cls.klass),
            (cls.hyunbo, cls.other),
        ):
            CourseEnrollment.objects.create(
                student=student,
                course=cls.course,
                klass=klass,
                status=CourseEnrollment.Status.ENROLLED,
            )

        mark = Attendance.objects.create
        mark(session=cls.weeks[0], student=cls.haneul, status=Attendance.Status.PRESENT)
        mark(session=cls.weeks[1], student=cls.haneul, status=Attendance.Status.ABSENT)
        mark(session=cls.weeks[2], student=cls.haneul, status=Attendance.Status.PRESENT)
        mark(session=cls.weeks[0], student=cls.seojun, status=Attendance.Status.PRESENT)
        mark(session=cls.weeks[2], student=cls.seojun, status=Attendance.Status.ABSENT_MAKEUP)
        # 3주차에 들어온 학생 — 앞 두 주차에는 기록이 없다(화면이 x 로 그린다)
        mark(session=cls.weeks[2], student=cls.jiwoo, status=Attendance.Status.PRESENT)
        # 화반 학생이 1주차만 이 반에서 들었다(현보)
        mark(session=cls.weeks[0], student=cls.hyunbo, status=Attendance.Status.ABSENT_ONSITE)

    def login(self, user):
        self.client.force_login(user)

    def rows(self, class_id=None):
        res = self.client.get(grid_url(class_id or self.klass.class_id))
        self.assertEqual(res.status_code, 200)
        body = res.json()
        return body, {r["name"]: r for r in body["students"]}

    def test_gate_is_attendance_entry(self):
        """조교가 여는 화면이다(FLOW 3-1) — `계정관리` 로 잠그면 주인이 못 연다."""
        url = grid_url(self.klass.class_id)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.login(self.haneul.user)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.login(self.assistant)
        self.assertEqual(self.client.get(url).status_code, 200)
        StaffFeatureGrant.objects.create(
            user=self.assistant, feature_key=FeatureKey.ATTENDANCE_ENTRY, is_granted=False
        )
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_unknown_class_is_404(self):
        self.login(self.admin)
        self.assertEqual(self.client.get(grid_url(999999)).status_code, 404)

    def test_cells_line_up_with_weeks(self):
        """칸은 주차와 **자리로** 맞는다 — 어긋나면 남의 주차 출결을 읽는다."""
        self.login(self.admin)
        body, by_name = self.rows()
        self.assertEqual([w["week_no"] for w in body["weeks"]], [1, 2, 3, 4])
        self.assertEqual(
            [w["session_id"] for w in body["weeks"]], [w.session_id for w in self.weeks]
        )
        for row in body["students"]:
            self.assertEqual(len(row["cells"]), len(body["weeks"]))
        self.assertEqual(by_name["김하늘"]["cells"], ["출석", "결석", "출석", None])
        self.assertEqual(body["klass"]["name"], "목 6.5 대치러셀")

    def test_no_record_before_the_first_one(self):
        """`x` 의 재료 — 첫 기록보다 앞선 칸은 **비어서** 내려간다(FLOW 3-1).

        `x` 는 저장하지도 내려보내지도 않는다. 화면이 "값이 있는 첫 칸"보다
        앞이면 x 로 그린다. 기록이 하나도 없는 학생은 앞선 칸이 없으므로 전부
        `미입력` 이지 x 가 아니다 — 아직 안 본 것이지 볼 것이 없는 것이 아니다.
        """
        self.login(self.admin)
        _, by_name = self.rows()
        self.assertEqual(by_name["박지우"]["cells"], [None, None, "출석", None])
        self.assertEqual(by_name["한서윤"]["cells"], [None, None, None, None])

    def test_student_of_another_class_keeps_his_line(self):
        """이 반에 기록이 있으면 수강이 다른 반이어도 줄이 남는다(FLOW 3-9·3-4).

        명단을 지금 수강으로만 뽑으면 반을 옮긴 학생의 지난 출결이 옛 반
        격자에서 통째로 사라진다 — 기록은 남는데 볼 자리가 없어진다.
        """
        self.login(self.admin)
        _, by_name = self.rows()
        self.assertEqual(by_name["최현보"]["cells"], ["결석(현보)", None, None, None])
        # 화반 격자에는 이 학생의 목반 기록이 섞이지 않는다
        _, other = self.rows(self.other.class_id)
        self.assertEqual(other["최현보"]["cells"], [])

    def test_withdrawn_student_stays_with_his_status(self):
        """퇴원생도 줄을 남긴다 — 다녔던 주차가 그 학생의 이력이다."""
        self.login(self.admin)
        _, by_name = self.rows()
        self.assertEqual(by_name["한서윤"]["enrollment_status"], "퇴원")

    def test_query_count_does_not_grow_with_the_grid(self):
        """학생 × 주차라 한 번만 새도 N+1 이다 — 늘려도 같은 수여야 한다.

        대표가 아니라 **관리자**로 잰다. 대표는 `effective_features` 를
        건너뛰어 기능키 조회 1건이 빠지므로 수가 달라진다.
        """
        self.login(self.admin)
        url = grid_url(self.klass.class_id)
        budget = 7  # 세션인증 2 + 기능키 1 + 반 1 + 회차 1 + 명단 1 + 출결 1
        with self.assertNumQueries(budget):
            self.client.get(url)

        for n in range(3):
            student = make_student(f"more-{n}", f"추가{n}")
            CourseEnrollment.objects.create(
                student=student,
                course=self.course,
                klass=self.klass,
                status=CourseEnrollment.Status.ENROLLED,
            )
            for week in self.weeks:
                Attendance.objects.create(
                    session=week, student=student, status=Attendance.Status.PRESENT
                )
        ClassSession.objects.create(
            klass=self.klass, week_no=5, session_date=datetime.date(2026, 10, 1)
        )
        with self.assertNumQueries(budget):
            self.client.get(url)

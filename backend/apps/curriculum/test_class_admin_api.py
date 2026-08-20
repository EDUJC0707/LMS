"""반 개설 API 테스트 — GET·POST /api/admin/classes (FLOW 1-2·1-3).

검증 축:
- 기능 게이트: 계정관리 키(FeatureRequired) — 조교 프리셋에 없어 403,
  delta 부여 시 허용. 학생·비로그인은 차단
- 개설: 커리와 반을 한 번에 / 이미 있는 커리에 반만 더하기 / 같은 커리에
  같은 반 이름은 거절
- 구분·과목(FLOW 1-2): 과목은 없으면 만들어지고, 구분은 값집합 밖을 거절한다
- 회차: 개강일에서 주 단위로 총주차만큼 — 1주차 9/4 · 2주차 9/11 · … ·
  10주차 11/6. 반의 주차가 곧 회차라 `ClassSession(klass, week_no)` 다
- 목록: 커리로 묶고, 반마다 진행 주차와 수강생 수
- 주차 수정(FLOW 1-3): 앞을 고치면 뒤가 따라 밀리고 번호는 안 움직인다.
  추가·삭제는 반에서만 하고 기록이 붙은 주차는 못 지운다
- 반 이동(FLOW 3-9): 수강의 반이 갈리고 지난 기록은 옛 반에 남는다
"""
import datetime
import json

from django.test import TestCase

from apps.accounts.features import FeatureKey
from apps.accounts.models import StaffFeatureGrant, Student, User
from apps.grades.models import Attendance, ClassSession

from .models import Class, Course, CourseEnrollment, CourseWeek, Subject

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
        "track": "수능",
        "subject": "통합과학",
        "course_name": "2026 여름 N제",
        "total_weeks": 10,
        "name": "목 6.5 대치러셀",
        "start_date": "2026-09-04",
    }

    def test_payssam_is_off_unless_the_form_turns_it_on(self):
        """교재값 수령처는 반을 만들 때 고른다(FLOW 1-2 · 2-7).

        기본값이 꺼짐(학원이 따로 받는다)인 이유: 안 나간 청구는 켜고 다시 보내면
        되지만, 잘못 나간 청구는 되돌려도 학부모가 이미 받았다.
        """
        default = Class.objects.get(pk=self.post_class(self.BODY).json()["class_id"])
        self.assertFalse(default.uses_payssam)

        res = self.post_class({**self.BODY, "name": "화 6.5 미래탐구", "uses_payssam": True})
        self.assertEqual(res.status_code, 201)
        self.assertTrue(res.json()["uses_payssam"])
        self.assertTrue(Class.objects.get(pk=res.json()["class_id"]).uses_payssam)

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

    def test_open_class_leaves_the_week_dates_to_the_class(self):
        """날짜는 반의 것이다 — 커리 주차에는 담지 않고 공개 시점만 찍는다."""
        body = self.post_class(self.BODY).json()
        course = Course.objects.get(pk=body["course_id"])
        weeks = list(CourseWeek.objects.filter(course=course).order_by("week_no"))
        self.assertEqual([w.start_date for w in weeks], [None] * 10)
        self.assertEqual([w.end_date for w in weeks], [None] * 10)
        # 개강 전에도 보여야 한다 — 공개 시점은 개강일이 아니라 반을 연 시각
        self.assertEqual(CourseWeek.objects.released().count(), 10)

    def test_open_class_releases_a_week_left_locked_on_an_old_course(self):
        """공개 근거 없이 만들어진 주차 — 반을 열 때 찍어야 잠긴 채로 남지 않는다."""
        course = Course.objects.create(name="옛 커리", total_weeks=2)
        CourseWeek.objects.create(course=course, week_no=1)
        self.post_class(
            {"course_id": course.course_id, "name": "목반", "start_date": "2026-09-04"}
        )
        week1 = CourseWeek.objects.get(course=course, week_no=1)
        self.assertIsNotNone(week1.release_at)

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
            # 구분은 잠겨 있다(FLOW 1-2) — 값집합 밖은 새 값이 되지 않는다
            {**self.BODY, "track": "수능(재종)"},
            {**self.BODY, "track": ""},
            {**self.BODY, "track": None},
            {**self.BODY, "subject": " "},
        ):
            with self.subTest(body=body):
                self.assertEqual(self.post_class(body).status_code, 400)
        self.assertEqual(Course.objects.count(), 0)
        self.assertEqual(Class.objects.count(), 0)
        self.assertEqual(ClassSession.objects.count(), 0)
        self.assertFalse(Subject.objects.filter(track="수능(재종)").exists())


class SubjectTests(ClassAdminFixtureMixin, TestCase):
    """구분·과목 — 과목은 신규 입력이 되고 구분은 잠겨 있다 (FLOW 1-2)."""

    def test_migration_seeded_the_flow_table(self):
        self.assertEqual(
            sorted(Subject.objects.values_list("track", "name")),
            sorted(
                [
                    ("수능", "통합과학"),
                    ("내신", "일반선택 생명과학"),
                    ("내신", "진로선택 생명과학 — 세포와 물질대사"),
                    ("내신", "진로선택 생명과학 — 생물의 유전"),
                ]
            ),
        )

    def test_new_course_carries_the_chosen_subject(self):
        res = self.post_class(
            {**OpenClassTests.BODY, "track": "내신", "subject": "일반선택 생명과학"}
        )
        self.assertEqual(res.status_code, 201)
        course = Course.objects.get(pk=res.json()["course_id"])
        self.assertEqual(course.subject.name, "일반선택 생명과학")
        self.assertEqual(course.subject.track, "내신")
        self.assertEqual(Subject.objects.count(), 4)  # 있던 과목을 다시 만들지 않는다

    def test_unknown_subject_name_creates_it(self):
        res = self.post_class({**OpenClassTests.BODY, "subject": "물리학Ⅰ"})
        self.assertEqual(res.status_code, 201)
        self.assertEqual(Subject.objects.count(), 5)
        self.assertEqual(Subject.objects.get(name="물리학Ⅰ").track, "수능")

    def test_same_name_under_the_other_track_is_a_different_subject(self):
        self.post_class(OpenClassTests.BODY)
        res = self.post_class(
            {**OpenClassTests.BODY, "track": "내신", "course_name": "내신 통합과학"}
        )
        self.assertEqual(res.status_code, 201)
        self.assertEqual(Subject.objects.filter(name="통합과학").count(), 2)

    def test_adding_a_class_to_an_existing_course_keeps_its_subject(self):
        first = self.post_class(OpenClassTests.BODY).json()
        res = self.post_class(
            {
                "course_id": first["course_id"],
                "name": "화 6.5 대치러셀",
                "start_date": "2026-09-02",
            }
        )
        self.assertEqual(res.status_code, 201)
        self.assertEqual(Course.objects.get(pk=first["course_id"]).subject.name, "통합과학")

    def test_list_serves_the_choices(self):
        body = self.get_classes().json()
        self.assertEqual(body["tracks"], ["수능", "내신"])
        self.assertIn({"track": "수능", "name": "통합과학"}, body["subjects"])


class ClassListTests(ClassAdminFixtureMixin, TestCase):
    """GET /api/admin/classes — 커리로 묶은 목록."""

    def test_groups_classes_under_their_course_with_counts(self):
        course = Course.objects.create(
            name="2026 여름 N제",
            total_weeks=10,
            subject=Subject.objects.get(track="수능", name="통합과학"),
        )
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
        self.assertEqual(group["subject"], "통합과학")
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
        self.assertEqual(self.get_classes().json()["courses"], [])


class ClassScheduleTests(ClassAdminFixtureMixin, TestCase):
    """반별 주차 — 날짜 수정 · 추가 · 삭제 (FLOW 1-3).

    검증 축:
    - 앞을 고치면 뒤가 같은 폭으로 따라 밀린다. **번호는 안 움직인다**
    - 다른 반은 그대로다 — 반마다 자기 날짜를 갖는다
    - 주차 추가·삭제는 반에서만. 커리 총주차는 안 바뀐다
    - **기록이 붙은 주차는 못 지운다** — 출결·과제가 CASCADE 로 같이 사라진다
    """

    def setUp(self):
        body = self.post_class(
            {
                "track": "수능",
                "subject": "통합과학",
                "course_name": "2026 여름 N제",
                "total_weeks": 10,
                "name": "목 6.5 대치러셀",
                "start_date": "2026-09-04",
            }
        ).json()
        self.course_id = body["course_id"]
        self.class_id = body["class_id"]
        self.klass = Class.objects.get(pk=self.class_id)

    def patch_week(self, week_no, session_date, class_id=None, user=None):
        self.client.force_login(user or self.admin)
        return self.client.patch(
            f"{URL}/{class_id or self.class_id}/sessions/{week_no}",
            data=json.dumps({"session_date": session_date}),
            content_type="application/json",
        )

    def dates(self, class_id=None):
        return {
            s.week_no: s.session_date
            for s in ClassSession.objects.filter(klass_id=class_id or self.class_id)
        }

    def test_moving_a_week_pushes_the_later_ones(self):
        res = self.patch_week(3, "2026-11-12")
        self.assertEqual(res.status_code, 200)
        dates = self.dates()
        # 1·2주차는 그대로, 3주차부터 8주(9/18 → 11/12) 밀린다
        self.assertEqual(dates[1], datetime.date(2026, 9, 4))
        self.assertEqual(dates[2], datetime.date(2026, 9, 11))
        self.assertEqual(dates[3], datetime.date(2026, 11, 12))
        self.assertEqual(dates[4], datetime.date(2026, 11, 19))
        self.assertEqual(dates[10], datetime.date(2026, 12, 31))
        # 번호는 안 움직인다 — 출결·성적·영상 권한이 번호로 붙어 있다
        self.assertEqual(sorted(dates), list(range(1, 11)))

    def test_a_week_can_move_back(self):
        self.patch_week(3, "2026-09-11")
        self.assertEqual(self.dates()[4], datetime.date(2026, 9, 18))

    def test_the_other_class_keeps_its_own_dates(self):
        second = self.post_class(
            {"course_id": self.course_id, "name": "화 6.5 대치러셀", "start_date": "2026-09-02"}
        ).json()
        self.patch_week(3, "2026-11-12")
        self.assertEqual(self.dates(second["class_id"])[3], datetime.date(2026, 9, 16))

    def test_unknown_week_is_rejected(self):
        self.assertEqual(self.patch_week(99, "2026-11-12").status_code, 400)

    def test_bad_date_is_rejected(self):
        self.assertEqual(self.patch_week(3, "11/12").status_code, 400)

    def test_unknown_class_is_404(self):
        self.assertEqual(self.patch_week(3, "2026-11-12", class_id=9999).status_code, 404)

    def test_adding_a_week_appends_after_the_last(self):
        self.client.force_login(self.admin)
        res = self.client.post(f"{URL}/{self.class_id}/sessions")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["sessions"][-1]["week_no"], 11)
        self.assertEqual(self.dates()[11], datetime.date(2026, 11, 13))
        # 커리 총주차는 안 바뀐다. 없던 커리 주차는 만들어 회차에 물린다
        self.assertEqual(Course.objects.get(pk=self.course_id).total_weeks, 10)
        self.assertEqual(CourseWeek.objects.filter(course_id=self.course_id).count(), 11)

    def test_removing_the_last_week(self):
        self.client.force_login(self.admin)
        res = self.client.delete(f"{URL}/{self.class_id}/sessions/10")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(sorted(self.dates()), list(range(1, 10)))
        # 커리 주차는 다른 반도 쓰므로 남는다
        self.assertEqual(Course.objects.get(pk=self.course_id).total_weeks, 10)
        self.assertEqual(CourseWeek.objects.filter(course_id=self.course_id).count(), 10)

    def test_only_the_last_week_can_be_removed(self):
        self.client.force_login(self.admin)
        res = self.client.delete(f"{URL}/{self.class_id}/sessions/5")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(len(self.dates()), 10)

    def test_a_week_with_records_cannot_be_removed(self):
        """출결이 달린 회차를 지우면 그 기록이 CASCADE 로 같이 사라진다."""
        student = Student.objects.create(
            user=make_user("sched-stu", User.Role.STUDENT, name="김하늘"),
            enrollment_status=Student.EnrollmentStatus.REGISTERED,
        )
        Attendance.objects.create(
            session=ClassSession.objects.get(klass=self.klass, week_no=10),
            student=student,
            status=Attendance.Status.PRESENT,
        )
        self.client.force_login(self.admin)
        res = self.client.delete(f"{URL}/{self.class_id}/sessions/10")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(len(self.dates()), 10)
        self.assertEqual(Attendance.objects.count(), 1)

    def test_assistant_without_feature_gets_403(self):
        self.assertEqual(
            self.patch_week(3, "2026-11-12", user=self.assistant).status_code, 403
        )


class ClassMoveTests(ClassAdminFixtureMixin, TestCase):
    """POST /api/admin/classes/{id}/students — 반 이동 (FLOW 3-9)."""

    def setUp(self):
        self.first = self.post_class(
            {
                "track": "수능",
                "subject": "통합과학",
                "course_name": "2026 여름 N제",
                "total_weeks": 3,
                "name": "목 6.5 대치러셀",
                "start_date": "2026-09-04",
            }
        ).json()
        self.second = self.post_class(
            {
                "course_id": self.first["course_id"],
                "name": "화 6.5 대치러셀",
                "start_date": "2026-09-02",
            }
        ).json()
        self.student = Student.objects.create(
            user=make_user("mv-stu", User.Role.STUDENT, name="박지우"),
            enrollment_status=Student.EnrollmentStatus.REGISTERED,
        )
        self.enrollment = CourseEnrollment.objects.create(
            student=self.student,
            course_id=self.first["course_id"],
            klass_id=self.first["class_id"],
        )

    def move(self, class_id, student_id=None, user=None):
        self.client.force_login(user or self.admin)
        return self.client.post(
            f"{URL}/{class_id}/students",
            data=json.dumps({"student_id": student_id or self.student.student_id}),
            content_type="application/json",
        )

    def test_move_swaps_the_class_on_the_enrollment(self):
        res = self.move(self.second["class_id"])
        self.assertEqual(res.status_code, 200)
        self.enrollment.refresh_from_db()
        self.assertEqual(self.enrollment.klass_id, self.second["class_id"])
        # 수강은 하나뿐 — 옛 반에 사본이 남지 않는다
        self.assertEqual(CourseEnrollment.objects.count(), 1)

    def test_moved_student_shows_on_the_new_class_roster_only(self):
        self.move(self.second["class_id"])
        self.client.force_login(self.admin)
        StaffFeatureGrant.objects.create(
            user=self.admin,
            feature_key=FeatureKey.ATTENDANCE_ENTRY,
            is_granted=True,
            granted_by=self.owner,
        )
        old = ClassSession.objects.get(klass_id=self.first["class_id"], week_no=2)
        new = ClassSession.objects.get(klass_id=self.second["class_id"], week_no=2)
        self.assertNotIn(
            self.student.student_id, self._roster(old.session_id)
        )
        self.assertIn(self.student.student_id, self._roster(new.session_id))

    def test_past_records_keep_the_student_on_the_old_roster(self):
        """지난 기록은 옛 반에 남는다 — 그 줄이 출결표에서 사라지면 안 된다."""
        session = ClassSession.objects.get(klass_id=self.first["class_id"], week_no=1)
        Attendance.objects.create(
            session=session, student=self.student, status=Attendance.Status.PRESENT
        )
        self.move(self.second["class_id"])
        StaffFeatureGrant.objects.create(
            user=self.admin,
            feature_key=FeatureKey.ATTENDANCE_ENTRY,
            is_granted=True,
            granted_by=self.owner,
        )
        self.assertIn(self.student.student_id, self._roster(session.session_id))

    def _roster(self, session_id):
        self.client.force_login(self.admin)
        res = self.client.get(f"/api/admin/attendance/sessions/{session_id}")
        self.assertEqual(res.status_code, 200)
        return [row["student_id"] for row in res.json()["students"]]

    def test_moving_to_a_class_of_another_course_is_rejected(self):
        other = self.post_class(
            {
                "track": "수능",
                "subject": "통합과학",
                "course_name": "겨울 N제",
                "total_weeks": 2,
                "name": "월반",
                "start_date": "2026-12-07",
            }
        ).json()
        self.assertEqual(self.move(other["class_id"]).status_code, 400)

    def test_moving_a_student_who_does_not_take_the_course_is_rejected(self):
        stranger = Student.objects.create(
            user=make_user("mv-out", User.Role.STUDENT, name="남남"),
            enrollment_status=Student.EnrollmentStatus.REGISTERED,
        )
        res = self.move(self.second["class_id"], student_id=stranger.student_id)
        self.assertEqual(res.status_code, 400)

    def test_moving_into_the_same_class_is_a_no_op(self):
        res = self.move(self.first["class_id"])
        self.assertEqual(res.status_code, 200)
        self.enrollment.refresh_from_db()
        self.assertEqual(self.enrollment.klass_id, self.first["class_id"])

    def test_detail_serves_the_weeks_and_the_roster(self):
        self.client.force_login(self.admin)
        data = self.client.get(f"{URL}/{self.first['class_id']}").json()
        self.assertEqual([w["week_no"] for w in data["sessions"]], [1, 2, 3])
        self.assertEqual(data["sessions"][0]["session_date"], "2026-09-04")
        self.assertEqual([s["name"] for s in data["students"]], ["박지우"])

    def test_assistant_without_feature_gets_403(self):
        self.assertEqual(
            self.move(self.second["class_id"], user=self.assistant).status_code, 403
        )

"""캘린더 홈 API 2차 슬라이스 테스트 — 학생 홈·학부모 홈 (PRD 3.2.0·3.4·§4).

검증 축:
- 역할 게이트(IsStudent/IsParent) — 1차 슬라이스 부품 재사용
- 상태 기반 노출(§4): 미등록 bare / 미래 주차 잠김 스텁 / 만료·회수 영상 미포함 /
  자격 없는 마감 유형 항목 미포함 / 타인 자녀 404(존재 비노출)
- 시간 의미론: Asia/Seoul 기준 today·D-n, 자정 경계
- 쿼리 효율: assertNumQueries 로 쿼리 수 고정(N+1 회귀 방지)

기준 시각은 `apps.curriculum.home.timezone.now` 를 patch 해 고정한다(KST 결정적).
"""
import datetime
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import Parent, ParentStudent, Student, User
from apps.clinic.models import ClinicRequest
from apps.grades.models import Attendance, ClassSession
from apps.payments.models import Order, Product
from apps.videos.models import MakeupGrant, Video, VideoGrant

from .models import Class, Course, CourseEnrollment, CourseWeek, WeekDayPlan

PASSWORD = "pw-Secret-77!"
STUDENT_HOME = "/api/student/home"
PARENT_HOME = "/api/parent/home"

# 기준 시각: 2026-07-22(수) 10:00 KST — mock 데이터와 같은 달
NOW = timezone.make_aware(datetime.datetime(2026, 7, 22, 10, 0))
TODAY = datetime.date(2026, 7, 22)


def freeze_now(at=NOW):
    """홈 서비스의 기준 시각을 고정한다(서비스 모듈 경유 timezone.now 만 patch)."""
    return mock.patch("apps.curriculum.home.timezone.now", return_value=at)


def make_user(login_id, role, name="사용자"):
    return User.objects.create_user(login_id=login_id, password=PASSWORD, name=name, role=role)


def make_student(login_id, name="김서연", status=Student.EnrollmentStatus.REGISTERED, **extra):
    user = make_user(login_id, User.Role.STUDENT, name=name)
    return Student.objects.create(
        user=user, matching_key=f"uid-{login_id}", enrollment_status=status, **extra
    )


def make_video(week, sequence_no=1, status=Video.Status.PUBLISHED):
    """그 주차의 복습영상 1개 — 지급 단위가 영상이라 권한을 걸려면 실체가 필요하다."""
    return Video.objects.create(
        course_week=week,
        title=f"{week.week_no}주차 복습영상 {sequence_no}",
        status=status,
        sequence_no=sequence_no,
    )


class HomeFixtureMixin:
    """로직엔제 10주 커리큘럼 축소판(1~5주차) — mock 데이터와 같은 그림.

    - 1~4주차: 시작일 경과(공개), 5주차: 미래 시작일(잠김)
    - 수업 요일: 수(3) — 회차 7/8(2주차)·7/22(4주차)
    - 복습영상: 2·3주차에 `공개` 영상 1개씩 — 권한이 영상 1개당 1행이라 지급 대상
    - 출결: 7/8 출석, 7/15 결석(별도 회차), 7/18 결석(현보)(별도 회차)
      — 7/18 은 2026-07-29 값집합 개편 전 `지각` 자리. 현보로 바꾼 이유는 캘린더가
      네 값을 **그대로** 내려보내는지와, 결석 계열이라도 **현보는 동보 신청
      대상이 아님**(absences 목록 제외)을 같이 잡기 위해서다.
    """

    @classmethod
    def setUpTestData(cls):
        cls.student = make_student("stu-home")
        cls.course = Course.objects.create(name="로직엔제")
        cls.klass = Class.objects.create(course=cls.course, name="고2 로직엔제 B반")
        cls.enrollment = CourseEnrollment.objects.create(
            student=cls.student, course=cls.course, klass=cls.klass, primary_weekday=3
        )
        starts = {
            1: datetime.date(2026, 6, 28),
            2: datetime.date(2026, 7, 5),
            3: datetime.date(2026, 7, 12),
            4: datetime.date(2026, 7, 19),
            5: datetime.date(2026, 7, 26),  # 미래 — 잠김
        }
        cls.weeks = {}
        for no, start in starts.items():
            cls.weeks[no] = CourseWeek.objects.create(
                course=cls.course,
                week_no=no,
                title=f"{no}주차",
                start_date=start,
                end_date=start + datetime.timedelta(days=6),
                offline_notice=f"{no}주차 공지",
            )
        # 마감 목록(영상만료)이 걸릴 대상 — 권한은 영상 1개당 1행이라(2026-08-04)
        # 주차만으로는 권한을 만들 수 없다. 2·3주차만 두면 충분하다.
        cls.videos = {no: make_video(cls.weeks[no]) for no in (2, 3)}
        WeekDayPlan.objects.create(
            week=cls.weeks[4], day_no=1, title="산과 염기 개념 강의 복습", content="p.36"
        )
        WeekDayPlan.objects.create(week=cls.weeks[4], day_no=2, title="워크북 p.36–43")
        # 잠긴 주차에도 학습계획을 심어 미노출을 검증한다
        WeekDayPlan.objects.create(week=cls.weeks[5], day_no=1, title="유출되면 안 되는 계획")

        cls.session_0708 = ClassSession.objects.create(
            session_date=datetime.date(2026, 7, 8), course_week=cls.weeks[2]
        )
        cls.session_0715 = ClassSession.objects.create(
            session_date=datetime.date(2026, 7, 15), course_week=cls.weeks[3]
        )
        cls.session_0718 = ClassSession.objects.create(
            session_date=datetime.date(2026, 7, 18), course_week=cls.weeks[3]
        )
        cls.session_0729 = ClassSession.objects.create(
            session_date=datetime.date(2026, 7, 29), course_week=cls.weeks[5]
        )
        cls.att_present = Attendance.objects.create(
            session=cls.session_0708, student=cls.student, status=Attendance.Status.PRESENT
        )
        cls.att_absent = Attendance.objects.create(
            session=cls.session_0715, student=cls.student, status=Attendance.Status.ABSENT
        )
        cls.att_onsite = Attendance.objects.create(
            session=cls.session_0718,
            student=cls.student,
            status=Attendance.Status.ABSENT_ONSITE,
        )

    def login_student(self):
        self.client.force_login(self.student.user)

    def get_home(self, query=""):
        with freeze_now():
            return self.client.get(STUDENT_HOME + query)


class StudentHomeAccessTests(HomeFixtureMixin, TestCase):
    """역할 게이트·입력 검증 — IsStudent 재사용, month 형식."""

    def test_anonymous_denied(self):
        self.assertEqual(self.client.get(STUDENT_HOME).status_code, 403)

    def test_parent_role_denied(self):
        parent_user = make_user("par-deny", User.Role.PARENT)
        self.client.force_login(parent_user)
        self.assertEqual(self.client.get(STUDENT_HOME).status_code, 403)

    def test_staff_role_denied(self):
        admin = make_user("adm-deny", User.Role.ADMIN)
        self.client.force_login(admin)
        self.assertEqual(self.client.get(STUDENT_HOME).status_code, 403)

    def test_invalid_month_returns_400(self):
        self.login_student()
        for bad in ("2026-13", "2026/07", "202607", "abcd-ef"):
            self.assertEqual(self.get_home(f"?month={bad}").status_code, 400, bad)

    def test_post_not_allowed(self):
        self.login_student()
        self.assertEqual(self.client.post(STUDENT_HOME).status_code, 405)


class StudentHomeBareTests(TestCase):
    """미등록(예비등록) — 첫 로그인 거의 bare (PRD §4)."""

    def setUp(self):
        self.student = make_student(
            "stu-bare", status=Student.EnrollmentStatus.PRE_REGISTERED
        )
        self.client.force_login(self.student.user)
        Product.objects.create(name="로직엔제 교재", price=45000)
        Product.objects.create(name="구판 교재", price=30000, is_active=False)

    def test_bare_response_has_no_calendar_or_deadlines(self):
        with freeze_now():
            res = self.client.get(STUDENT_HOME)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["student"]["enrollment_status"], "예비등록")
        self.assertNotIn("calendar", data)
        self.assertNotIn("deadlines", data)
        self.assertNotIn("course", data)

    def test_bare_response_lists_active_products_only(self):
        with freeze_now():
            data = self.client.get(STUDENT_HOME).json()
        names = [p["name"] for p in data["purchasable_products"]]
        self.assertEqual(names, ["로직엔제 교재"])  # 판매 중지 교재 미포함

    def test_withdrawn_student_also_bare(self):
        # 닫힘이 기본값 — 퇴원 상태도 전체 캘린더를 열지 않는다
        self.student.enrollment_status = Student.EnrollmentStatus.WITHDRAWN
        self.student.save(update_fields=["enrollment_status"])
        with freeze_now():
            data = self.client.get(STUDENT_HOME).json()
        self.assertNotIn("calendar", data)

    def test_bare_query_count(self):
        with freeze_now(), self.assertNumQueries(5):
            # 세션 + user + student + 반 이름 + products
            # 반 이름은 학생 1명분 고정 1회다 — 미등록이라 결과는 비지만 묻기는 한다
            self.client.get(STUDENT_HOME)


class StudentHomeCalendarTests(HomeFixtureMixin, TestCase):
    """calendar.days(출결 도장·예정 수업)·weeks(공개/잠김)·진행 표기."""

    def test_student_block_and_month_defaults(self):
        self.login_student()
        data = self.get_home().json()
        self.assertEqual(data["month"], "2026-07")
        self.assertEqual(data["today"], "2026-07-22")
        self.assertEqual(
            data["student"],
            {
                "student_id": self.student.student_id,
                "name": "김서연",
                "current_class": "고2 로직엔제 B반",
                "enrollment_status": "등록",
            },
        )

    def test_today_follows_seoul_date_across_utc_midnight(self):
        # KST 7/23 00:30 = UTC 7/22 15:30 — today 는 서울 날짜여야 한다
        self.login_student()
        kst_after_midnight = timezone.make_aware(datetime.datetime(2026, 7, 23, 0, 30))
        with freeze_now(kst_after_midnight):
            data = self.client.get(STUDENT_HOME).json()
        self.assertEqual(data["today"], "2026-07-23")
        self.assertEqual(data["month"], "2026-07")

    def test_days_carry_attendance_stamps_and_sessions(self):
        self.login_student()
        days = {d["date"]: d for d in self.get_home().json()["calendar"]["days"]}
        self.assertEqual(days["2026-07-08"]["attendance"], "출석")
        self.assertEqual(days["2026-07-15"]["attendance"], "결석")
        self.assertEqual(days["2026-07-18"]["attendance"], "결석(현보)")
        self.assertTrue(days["2026-07-08"]["has_class_session"])
        # 미래 예정 수업일 — 출결 도장 없이 예정만 표시
        self.assertIsNone(days["2026-07-29"]["attendance"])
        self.assertTrue(days["2026-07-29"]["has_class_session"])
        # 아무 일도 없는 날은 항목 자체가 없다(희소 리스트)
        self.assertNotIn("2026-07-10", days)

    def test_days_carry_attendance_id_for_makeup_request(self):
        # 동보 신청(POST /api/student/makeup-request)의 body 키 — 화면에서
        # 결석 칸을 눌러 바로 신청하려면 이 값이 응답에 있어야 한다
        self.login_student()
        days = {d["date"]: d for d in self.get_home().json()["calendar"]["days"]}
        self.assertEqual(days["2026-07-15"]["attendance_id"], self.att_absent.id)
        self.assertEqual(days["2026-07-08"]["attendance_id"], self.att_present.id)
        # 출결이 없는 예정일은 null(키는 존재 — 프런트 분기 단순화)
        self.assertIsNone(days["2026-07-29"]["attendance_id"])

    def test_absent_day_carries_makeup_status(self):
        # 중복 신청 버튼 차단 근거 — 학부모 absences[].makeup_status 와 동일 형태
        self.login_student()
        days = {d["date"]: d for d in self.get_home().json()["calendar"]["days"]}
        self.assertIsNone(days["2026-07-15"]["makeup_status"])
        MakeupGrant.objects.create(
            student=self.student,
            attendance=self.att_absent,
            source=MakeupGrant.Source.STUDENT_REQUEST,
        )
        days = {d["date"]: d for d in self.get_home().json()["calendar"]["days"]}
        self.assertEqual(days["2026-07-15"]["makeup_status"], "신청")
        # 결석 아닌 날은 동보 개념 자체가 없다 — 항상 null
        self.assertIsNone(days["2026-07-08"]["makeup_status"])

    def test_makeup_status_takes_latest_request_after_rejection(self):
        # 거절 후 재신청 — 최신 신청(makeup_id 최대)이 화면 상태다
        self.login_student()
        MakeupGrant.objects.create(
            student=self.student,
            attendance=self.att_absent,
            source=MakeupGrant.Source.STUDENT_REQUEST,
            status=MakeupGrant.Status.REJECTED,
        )
        MakeupGrant.objects.create(
            student=self.student,
            attendance=self.att_absent,
            source=MakeupGrant.Source.STUDENT_REQUEST,
        )
        days = {d["date"]: d for d in self.get_home().json()["calendar"]["days"]}
        self.assertEqual(days["2026-07-15"]["makeup_status"], "신청")

    def test_month_param_filters_days(self):
        self.login_student()
        ClassSession.objects.create(
            session_date=datetime.date(2026, 6, 30), course_week=self.weeks[1]
        )
        days = {d["date"] for d in self.get_home("?month=2026-06").json()["calendar"]["days"]}
        self.assertIn("2026-06-30", days)
        self.assertNotIn("2026-07-08", days)

    def test_released_weeks_carry_label_notice_and_plans(self):
        self.login_student()
        weeks = {w["week_no"]: w for w in self.get_home().json()["calendar"]["weeks"]}
        week4 = weeks[4]
        self.assertFalse(week4["locked"])
        self.assertEqual(week4["label"], "로직엔제 4주차")
        self.assertEqual(week4["offline_notice"], "4주차 공지")
        self.assertEqual(week4["start_date"], "2026-07-19")
        self.assertEqual(
            [p["day_no"] for p in week4["day_plans"]], [1, 2]
        )
        self.assertEqual(week4["day_plans"][0]["title"], "산과 염기 개념 강의 복습")

    def test_future_week_is_locked_stub_without_content(self):
        # §4 콘텐츠 게이팅 — 미래 주차는 존재만(week_no+locked), 내용 없음
        self.login_student()
        weeks = {w["week_no"]: w for w in self.get_home().json()["calendar"]["weeks"]}
        self.assertEqual(weeks[5], {"week_no": 5, "locked": True})

    def test_early_release_overrides_future_start(self):
        # released() 계약 위임 확인 — release_at 조기 공개 시 내용 노출
        self.login_student()
        self.weeks[5].release_at = NOW - datetime.timedelta(hours=1)
        self.weeks[5].save(update_fields=["release_at"])
        weeks = {w["week_no"]: w for w in self.get_home().json()["calendar"]["weeks"]}
        self.assertFalse(weeks[5]["locked"])
        self.assertEqual(weeks[5]["day_plans"][0]["title"], "유출되면 안 되는 계획")

    def test_progress_current_and_total_weeks(self):
        self.login_student()
        course = self.get_home().json()["course"]
        self.assertEqual(course["name"], "로직엔제")
        self.assertEqual(course["current_week"], 4)
        self.assertEqual(course["total_weeks"], 5)
        self.assertEqual(course["class_weekdays"], [3])

    def test_no_enrollment_returns_empty_calendar(self):
        # 등록 상태지만 수강 배정 전 — 과목 블록 없이 빈 캘린더(닫힘 기본값)
        other = make_student("stu-noenroll")
        self.client.force_login(other.user)
        data = self.get_home().json()
        self.assertIsNone(data["course"])
        self.assertEqual(data["calendar"]["weeks"], [])

    def test_query_count_fixed(self):
        self.login_student()
        VideoGrant.objects.create(
            student=self.student,
            video=self.videos[3],
            source=VideoGrant.Source.ATTENDANCE_AUTO,
            attendance=self.att_present,
            granted_at=NOW - datetime.timedelta(days=6),
            expires_at=NOW + datetime.timedelta(days=1),
        )
        ClinicRequest.objects.create(
            student=self.student,
            requested_date=TODAY,
            requested_time=datetime.time(17, 0),
            status=ClinicRequest.Status.APPROVED,
        )
        Order.objects.create(
            student=self.student,
            product=Product.objects.create(name="교재", price=45000),
            amount=45000,
        )
        # 12 → 13 (2026-07-28): 결석 칸의 makeup_status 를 위한 동보 조회 1건.
        # 결석 수와 무관한 IN 조회 1회이며 학부모 홈과 공유한다(N+1 아님).
        with freeze_now(), self.assertNumQueries(13):
            res = self.client.get(STUDENT_HOME)
        self.assertEqual(len(res.json()["deadlines"]), 3)

    def test_no_makeup_query_when_month_has_no_absence(self):
        # 결석이 없으면 동보 조회 자체가 없다 — 위 13건에서 정확히 1건이 빠진다
        self.login_student()
        with freeze_now(), self.assertNumQueries(12):
            res = self.client.get(STUDENT_HOME + "?month=2026-08")
        self.assertEqual(res.json()["calendar"]["days"], [])


class StudentHomeDeadlineTests(HomeFixtureMixin, TestCase):
    """deadlines[] — 마감 임박 순, 자격 없는 유형 항목 미포함, D-n 경계."""

    def setUp(self):
        self.login_student()

    def _deadlines(self):
        return self.get_home().json()["deadlines"]

    def test_no_eligible_items_yields_empty_list(self):
        # 클리닉 배정·활성 영상 권한·미결제 주문이 전무 → 항목 자체 미포함
        # (영상은 픽스처에 있다 — 마감을 만드는 것은 영상이 아니라 권한이다)
        self.assertEqual(self._deadlines(), [])

    def test_clinic_only_approved_upcoming_included(self):
        ClinicRequest.objects.create(
            student=self.student,
            requested_date=TODAY,
            requested_time=datetime.time(17, 0),
            status=ClinicRequest.Status.APPROVED,
        )
        ClinicRequest.objects.create(  # 대기 상태 — 미포함
            student=self.student,
            requested_date=TODAY + datetime.timedelta(days=1),
            requested_time=datetime.time(19, 0),
        )
        ClinicRequest.objects.create(  # 지난 배정 — 미포함
            student=self.student,
            requested_date=TODAY - datetime.timedelta(days=1),
            requested_time=datetime.time(19, 0),
            status=ClinicRequest.Status.APPROVED,
        )
        items = self._deadlines()
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item["kind"], "클리닉")
        self.assertEqual(item["date"], "2026-07-22")
        self.assertEqual(item["start_time"], "17:00")
        self.assertEqual(item["d_day"], 0)
        self.assertNotIn("conference_url", item)  # 링크 자체는 시작 5분 전 규칙 — 미포함

    def test_clinic_link_active_from_five_minutes_before(self):
        ClinicRequest.objects.create(
            student=self.student,
            requested_date=TODAY,
            requested_time=datetime.time(17, 0),
            status=ClinicRequest.Status.APPROVED,
        )
        at_16_54 = timezone.make_aware(datetime.datetime(2026, 7, 22, 16, 54))
        at_16_55 = timezone.make_aware(datetime.datetime(2026, 7, 22, 16, 55))
        with freeze_now(at_16_54):
            self.assertFalse(self.client.get(STUDENT_HOME).json()["deadlines"][0]["link_active"])
        with freeze_now(at_16_55):
            self.assertTrue(self.client.get(STUDENT_HOME).json()["deadlines"][0]["link_active"])

    def test_video_deadline_dday_and_midnight_boundary(self):
        # 내일 자정(7/23 00:00) 만료 → 아직 활성, D-1(서울 날짜 기준)
        VideoGrant.objects.create(
            student=self.student,
            video=self.videos[3],
            source=VideoGrant.Source.ATTENDANCE_AUTO,
            attendance=self.att_present,
            granted_at=NOW - datetime.timedelta(days=6),
            expires_at=timezone.make_aware(datetime.datetime(2026, 7, 23, 0, 0)),
        )
        items = self._deadlines()
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item["kind"], "영상만료")
        # 주차는 권한이 아니라 **영상**에서 온다(권한은 영상 1개를 가리킬 뿐)
        self.assertEqual(item["week_no"], 3)
        self.assertEqual(item["due_date"], "2026-07-23")
        self.assertEqual(item["d_day"], 1)

    def test_video_expiring_today_is_dday_zero(self):
        VideoGrant.objects.create(
            student=self.student,
            video=self.videos[3],
            source=VideoGrant.Source.ATTENDANCE_AUTO,
            granted_at=NOW - datetime.timedelta(days=6),
            expires_at=timezone.make_aware(datetime.datetime(2026, 7, 22, 23, 0)),
        )
        self.assertEqual(self._deadlines()[0]["d_day"], 0)

    def test_one_row_per_week_however_many_videos(self):
        """영상이 여러 개여도 영상만료는 **주차당 한 줄**이다(2026-08-04 지급 단위 개정).

        권한 행은 영상마다 생기지만 학생이 묻는 것은 "언제까지 볼 수 있나" 하나다.
        영상 수만큼 같은 날짜를 반복하면 마감 목록이 아니라 영상 목록이 된다.
        """
        expires_at = timezone.make_aware(datetime.datetime(2026, 7, 23, 12, 0))
        videos = [self.videos[3], make_video(self.weeks[3], 2), make_video(self.weeks[3], 3)]
        for video in videos:
            VideoGrant.objects.create(
                student=self.student,
                video=video,
                source=VideoGrant.Source.ATTENDANCE_AUTO,
                granted_at=NOW - datetime.timedelta(days=6),
                expires_at=expires_at,
            )
        self.assertEqual(
            VideoGrant.objects.filter(student=self.student).count(), len(videos)
        )
        items = self._deadlines()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["kind"], "영상만료")
        self.assertEqual(items[0]["week_no"], 3)
        self.assertEqual(items[0]["due_date"], "2026-07-23")

    def test_same_week_different_expiry_stays_separate_rows(self):
        """묶는 축은 주차가 아니라 (주차, 만료) 다 — 기한이 갈리면 별개 마감이다."""
        VideoGrant.objects.create(
            student=self.student,
            video=self.videos[3],
            source=VideoGrant.Source.ATTENDANCE_AUTO,
            granted_at=NOW - datetime.timedelta(days=6),
            expires_at=timezone.make_aware(datetime.datetime(2026, 7, 23, 12, 0)),
        )
        VideoGrant.objects.create(  # 같은 주차 다른 영상을 나중에 수동 지급
            student=self.student,
            video=make_video(self.weeks[3], 2),
            source=VideoGrant.Source.MANUAL,
            granted_at=NOW,
            expires_at=timezone.make_aware(datetime.datetime(2026, 7, 29, 12, 0)),
        )
        items = self._deadlines()
        self.assertEqual([i["due_date"] for i in items], ["2026-07-23", "2026-07-29"])
        self.assertEqual({i["week_no"] for i in items}, {3})

    def test_expired_and_revoked_grants_not_included(self):
        VideoGrant.objects.create(  # 이미 만료(expires_at == now 포함 안 함)
            student=self.student,
            video=self.videos[2],
            source=VideoGrant.Source.ATTENDANCE_AUTO,
            granted_at=NOW - datetime.timedelta(days=7),
            expires_at=NOW,
        )
        VideoGrant.objects.create(  # 회수됨
            student=self.student,
            video=self.videos[3],
            source=VideoGrant.Source.MANUAL,
            granted_at=NOW - datetime.timedelta(days=1),
            expires_at=NOW + datetime.timedelta(days=6),
            revoked_at=NOW - datetime.timedelta(hours=1),
        )
        self.assertEqual(self._deadlines(), [])

    def test_unpaid_order_included_paid_excluded(self):
        product = Product.objects.create(name="로직엔제 교재", price=45000)
        paid_product = Product.objects.create(name="워크북", price=20000)
        Order.objects.create(student=self.student, product=product, amount=45000)
        Order.objects.create(
            student=self.student,
            product=paid_product,
            amount=20000,
            status=Order.Status.PAID,
        )
        items = self._deadlines()
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item["kind"], "교재결제")
        self.assertEqual(item["product_name"], "로직엔제 교재")
        self.assertEqual(item["amount"], 45000)
        # 결제 기한 컬럼은 스키마에 없다 — due 없음(D-n 미산출)을 명시적으로 내린다
        self.assertIsNone(item["due_date"])
        self.assertIsNone(item["d_day"])

    def test_sorted_by_due_ascending_payment_last(self):
        Order.objects.create(
            student=self.student,
            product=Product.objects.create(name="교재", price=45000),
            amount=45000,
        )
        VideoGrant.objects.create(
            student=self.student,
            video=self.videos[3],
            source=VideoGrant.Source.ATTENDANCE_AUTO,
            granted_at=NOW - datetime.timedelta(days=6),
            expires_at=timezone.make_aware(datetime.datetime(2026, 7, 23, 12, 0)),
        )
        ClinicRequest.objects.create(
            student=self.student,
            requested_date=TODAY,
            requested_time=datetime.time(17, 0),
            status=ClinicRequest.Status.APPROVED,
        )
        kinds = [i["kind"] for i in self._deadlines()]
        self.assertEqual(kinds, ["클리닉", "영상만료", "교재결제"])


class ParentHomeTests(HomeFixtureMixin, TestCase):
    """학부모 홈 — 자녀 소유 검증(404)·공용 페이로드 재사용·결제/결석·동보."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.parent_user = make_user("par-home", User.Role.PARENT, name="김학부모")
        cls.parent = Parent.objects.create(user=cls.parent_user, phone="010-1234-5678")
        ParentStudent.objects.create(parent=cls.parent, student=cls.student)
        # 남의 자녀(소유 검증 대상)
        cls.other_student = make_student("stu-other", name="박타인")

    def setUp(self):
        self.client.force_login(self.parent_user)

    def get_parent_home(self, query=""):
        with freeze_now():
            return self.client.get(PARENT_HOME + query)

    def test_student_role_denied(self):
        self.client.force_login(self.student.user)
        self.assertEqual(self.client.get(PARENT_HOME).status_code, 403)

    def test_defaults_to_first_child(self):
        res = self.get_parent_home()
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["student"]["student_id"], self.student.student_id)
        self.assertEqual(data["student"]["name"], "김서연")
        # 학생 홈과 같은 구성 — 캘린더·마감 공용 로직 재사용
        self.assertIn("calendar", data)
        self.assertIn("deadlines", data)
        self.assertEqual(
            {w["week_no"] for w in data["calendar"]["weeks"] if w["locked"]}, {5}
        )

    def test_other_students_child_is_404(self):
        # 타인 자녀 — 존재 비노출(404, 메시지 동일)
        res = self.get_parent_home(f"?student_id={self.other_student.student_id}")
        self.assertEqual(res.status_code, 404)

    def test_unknown_student_id_is_404(self):
        self.assertEqual(self.get_parent_home("?student_id=999999").status_code, 404)

    def test_malformed_student_id_is_400(self):
        self.assertEqual(self.get_parent_home("?student_id=abc").status_code, 400)

    def test_parent_without_children_is_404(self):
        lone_user = make_user("par-lone", User.Role.PARENT)
        Parent.objects.create(user=lone_user, phone="010-0000-0000")
        self.client.force_login(lone_user)
        self.assertEqual(self.client.get(PARENT_HOME).status_code, 404)

    def test_selected_child_by_student_id(self):
        second = make_student("stu-second", name="김동생")
        ParentStudent.objects.create(parent=self.parent, student=second)
        res = self.get_parent_home(f"?student_id={second.student_id}")
        self.assertEqual(res.json()["student"]["name"], "김동생")

    def test_payment_status_lists_all_orders(self):
        product = Product.objects.create(name="로직엔제 교재", price=45000)
        Order.objects.create(
            student=self.student,
            product=product,
            amount=45000,
            status=Order.Status.PAID,
        )
        data = self.get_parent_home().json()
        self.assertEqual(len(data["payment_status"]), 1)
        entry = data["payment_status"][0]
        self.assertEqual(entry["product_name"], "로직엔제 교재")
        self.assertEqual(entry["status"], "결제완료")

    def test_absences_carry_makeup_status(self):
        MakeupGrant.objects.create(
            student=self.student,
            attendance=self.att_absent,
            source=MakeupGrant.Source.PARENT_REQUEST,
            requested_by=self.parent_user,
        )
        data = self.get_parent_home().json()
        self.assertEqual(len(data["absences"]), 1)
        entry = data["absences"][0]
        self.assertEqual(entry["date"], "2026-07-15")
        self.assertEqual(entry["makeup_status"], "신청")

    def test_absence_without_makeup_is_null_status(self):
        entry = self.get_parent_home().json()["absences"][0]
        self.assertEqual(entry["date"], "2026-07-15")
        self.assertIsNone(entry["makeup_status"])

    def test_absences_carry_attendance_id(self):
        # 학부모 동보 신청(POST /api/parent/makeup-request) body 키
        entry = self.get_parent_home().json()["absences"][0]
        self.assertEqual(entry["attendance_id"], self.att_absent.id)

    def test_absences_exclude_onsite_makeup_absence(self):
        """`absences` 는 결석 목록이 아니라 **동보 신청 목록**이다.

        `결석(현보)` 는 현장 보강이 끝난 결석이라 동보 신청 대상이 아니다 —
        여기 띄우면 학부모가 신청 버튼을 누르고 400 을 맞는다. 캘린더 도장
        (days[].attendance)에는 그대로 보이므로 결석 사실이 감춰지지도 않는다.
        """
        dates = [a["date"] for a in self.get_parent_home().json()["absences"]]
        self.assertEqual(dates, ["2026-07-15"])

    def test_absences_include_makeup_absence_with_granted_status(self):
        """`결석(동보)` 는 남긴다 — 중복 신청 차단 근거(makeup_status)가 필요하다."""
        self.att_absent.status = Attendance.Status.ABSENT_MAKEUP
        self.att_absent.save(update_fields=["status"])
        MakeupGrant.objects.create(
            student=self.student,
            attendance=self.att_absent,
            source=MakeupGrant.Source.ADMIN_CHECK,
            status=MakeupGrant.Status.GRANTED,
        )
        entry = self.get_parent_home().json()["absences"][0]
        self.assertEqual(entry["date"], "2026-07-15")
        self.assertEqual(entry["makeup_status"], "지급완료")

    def test_parent_days_carry_attendance_id_and_makeup_status(self):
        # 학생 홈과 같은 조립부(_days) — 형태 동일
        days = {d["date"]: d for d in self.get_parent_home().json()["calendar"]["days"]}
        self.assertEqual(days["2026-07-15"]["attendance_id"], self.att_absent.id)
        self.assertIsNone(days["2026-07-15"]["makeup_status"])

    def test_bare_child_keeps_payment_status(self):
        # 미등록 자녀 — bare 구성 + 결제 상태(학부모 결제 액션 근거)는 유지
        bare_child = make_student(
            "stu-parbare", name="김막내", status=Student.EnrollmentStatus.PRE_REGISTERED
        )
        ParentStudent.objects.create(parent=self.parent, student=bare_child)
        Product.objects.create(name="로직엔제 교재", price=45000)
        data = self.get_parent_home(f"?student_id={bare_child.student_id}").json()
        self.assertNotIn("calendar", data)
        self.assertNotIn("deadlines", data)
        self.assertNotIn("absences", data)
        self.assertEqual(len(data["purchasable_products"]), 1)
        self.assertEqual(data["payment_status"], [])

    def test_read_only_post_denied(self):
        self.assertEqual(self.client.post(PARENT_HOME).status_code, 405)

    def test_query_count_fixed(self):
        VideoGrant.objects.create(
            student=self.student,
            video=self.videos[3],
            source=VideoGrant.Source.ATTENDANCE_AUTO,
            granted_at=NOW - datetime.timedelta(days=6),
            expires_at=NOW + datetime.timedelta(days=1),
        )
        MakeupGrant.objects.create(
            student=self.student,
            attendance=self.att_absent,
            source=MakeupGrant.Source.PARENT_REQUEST,
        )
        with freeze_now(), self.assertNumQueries(14):
            res = self.client.get(PARENT_HOME)
        self.assertEqual(res.status_code, 200)

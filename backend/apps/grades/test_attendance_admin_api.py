"""출결 입력 API 테스트 — SSOT 쓰기 + 파생 트리거 (PRD 3.1.6·3.1.4①·3.2.3).

검증 축:
- 기능 키 게이트: 출결 조회/입력·퇴원 처리 = 출결입력, 동보 = 영상지급관리
- 회차 목록/상세: 강좌·주차·날짜, 명단(수강생 + **퇴원생도 남김**), 출결 값, 집계
- SSOT 쓰기: 부분/전체 upsert, 정정 시 updated_at 앱 레이어 갱신(auto_now 아님)
- 파생 트리거(동기·같은 트랜잭션) — 값집합 4종(2026-07-29 개편) 기준:
  ① 출석·결석(현보) → VideoGrant(출석자동, 그 회차 주차의 `공개` 영상마다, +7일)
     / 정정 시 revoke·재활성
  ② 결석 → AbsenceCounseling 대기열 / 결석 아님으로 정정 시 미통화 대기 행만 정리
  ③ 결석(동보) → MakeupGrant(지급완료) + VideoGrant(동보) / 정정 시 revoke·재활성
- 동보 체인: 관리자 체크 = 출결을 `결석(동보)` 로 올리는 것과 같다(입구 단일화)
- 쿼리 효율: assertNumQueries 고정(N+1 회귀 방지)

**지급 단위는 영상 1개다**(2026-08-04 개정 — 구 "주차 묶음"). 한 출결이 그 회차
주차의 `공개` 영상 수만큼 권한 행을 낳으므로, 권한 개수를 세는 단언은
`len(self.w2_videos)` 처럼 픽스처의 공개 영상 수를 근거로 쓴다(숫자를 직접 박지
않는다). 회수·재활성도 그 근거의 **전 행**에 걸려야 한다 — 한 행만 끄면 학생에게
나머지 영상이 그대로 열려 있다.

기준 시각은 `apps.grades.attendance_admin.timezone.now` 를 patch 해 고정한다
(2차 슬라이스 home 선례 — Asia/Seoul 의미론).
"""
import datetime
import json
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from apps.accounts.features import FeatureKey
from apps.accounts.models import StaffFeatureGrant, Student, User
from apps.boards.models import AbsenceCounseling
from apps.curriculum.models import Course, CourseEnrollment, CourseWeek
from apps.videos.models import MakeupGrant, Video, VideoGrant

from .models import Attendance, ClassSession

PASSWORD = "pw-Secret-77!"
SESSIONS_URL = "/api/admin/attendance/sessions"
MAKEUP_URL = "/api/admin/attendance/makeup"
WITHDRAW_URL = "/api/admin/attendance/withdraw"

# 기준 시각: 2026-07-22(수) 22:00 KST — 수업 당일 성적처리 후 출결 입력 시점
NOW = timezone.make_aware(datetime.datetime(2026, 7, 22, 22, 0))
GRANT_DURATION = datetime.timedelta(days=7)


def freeze_now(at=NOW):
    """출결 서비스의 기준 시각 고정(서비스 모듈 경유 timezone.now 만 patch)."""
    return mock.patch("apps.grades.attendance_admin.timezone.now", return_value=at)


def make_user(login_id, role, name="사용자"):
    return User.objects.create_user(login_id=login_id, password=PASSWORD, name=name, role=role)


def make_student(login_id, name, status=Student.EnrollmentStatus.REGISTERED):
    user = make_user(login_id, User.Role.STUDENT, name=name)
    return Student.objects.create(
        user=user, matching_key=f"uid-{login_id}", enrollment_status=status
    )


class AttendanceAdminFixtureMixin:
    """로직엔제 강좌 축소판 — 수강생 3 + 퇴원 1 + 타강좌 1, 회차 2개(주차 매핑).

    2주차에는 `공개` 영상 2개 + `준비중` 1개를 둔다 — 지급 단위가 영상이 된 뒤로
    "권한 몇 행이 나야 하는가"의 근거가 이 목록이고, 준비중 영상이 섞여 있어야
    "`공개` 인 것에만 권한이 난다"는 지급 시점 계약이 실제로 검증된다.
    1주차 영상 1개는 지급이 **그 회차 주차** 영상에만 나는지를 가른다.
    """

    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user("owner-1", User.Role.OWNER, name="대표")
        cls.admin = make_user("admin-1", User.Role.ADMIN, name="관리자")
        cls.assistant = make_user("assist-1", User.Role.ASSISTANT, name="조교")

        cls.course = Course.objects.create(name="로직엔제")
        cls.other_course = Course.objects.create(name="파이널")
        cls.week1 = CourseWeek.objects.create(
            course=cls.course, week_no=1, title="1주차", start_date=datetime.date(2026, 7, 12)
        )
        cls.week2 = CourseWeek.objects.create(
            course=cls.course, week_no=2, title="2주차", start_date=datetime.date(2026, 7, 19)
        )
        cls.session_w1 = ClassSession.objects.create(
            session_date=datetime.date(2026, 7, 15), session_no=1, course_week=cls.week1
        )
        cls.session_w2 = ClassSession.objects.create(
            session_date=datetime.date(2026, 7, 22), session_no=2, course_week=cls.week2
        )
        # 주차 미매핑 회차 — 명단 산정 불가 케이스
        cls.session_noweek = ClassSession.objects.create(
            session_date=datetime.date(2026, 7, 29), session_no=3
        )

        cls.w2_videos = [
            Video.objects.create(
                course_week=cls.week2,
                title="2주차 1강",
                status=Video.Status.PUBLISHED,
                sequence_no=1,
            ),
            Video.objects.create(
                course_week=cls.week2,
                title="2주차 2강",
                status=Video.Status.PUBLISHED,
                sequence_no=2,
            ),
        ]
        cls.w2_preparing = Video.objects.create(
            course_week=cls.week2,
            title="2주차 3강",
            status=Video.Status.PREPARING,
            sequence_no=3,
        )
        cls.w1_video = Video.objects.create(
            course_week=cls.week1,
            title="1주차 1강",
            status=Video.Status.PUBLISHED,
            sequence_no=1,
        )

        cls.s1 = make_student("stu-1", "김서연")
        cls.s2 = make_student("stu-2", "이준호")
        cls.s3 = make_student("stu-3", "박민지")
        cls.s_withdrawn = make_student(
            "stu-out", "정퇴원", status=Student.EnrollmentStatus.WITHDRAWN
        )
        cls.s_other = make_student("stu-etc", "최타반")
        for student in (cls.s1, cls.s2, cls.s3, cls.s_withdrawn):
            CourseEnrollment.objects.create(student=student, course=cls.course)
        CourseEnrollment.objects.create(student=cls.s_other, course=cls.other_course)

    def login(self, user):
        self.client.force_login(user)

    def w2_video_ids(self):
        """2주차 지급 대상 영상 id — `published_videos_of` 와 같은 정렬(차시 순)."""
        return [v.video_id for v in self.w2_videos]

    def detail_url(self, session_id):
        return f"{SESSIONS_URL}/{session_id}"

    def put_attendance(self, session_id, entries, at=NOW):
        with freeze_now(at):
            return self.client.put(
                self.detail_url(session_id),
                data=json.dumps(entries),
                content_type="application/json",
            )

    def post_makeup(self, body, at=NOW):
        with freeze_now(at):
            return self.client.post(
                MAKEUP_URL, data=json.dumps(body), content_type="application/json"
            )

    def post_withdraw(self, body, at=NOW):
        with freeze_now(at):
            return self.client.post(
                WITHDRAW_URL, data=json.dumps(body), content_type="application/json"
            )


class AttendanceAdminAccessTests(AttendanceAdminFixtureMixin, TestCase):
    """기능 키 게이트 — 출결입력(조회·입력) / 영상지급관리(동보)."""

    def test_anonymous_is_denied(self):
        self.assertEqual(self.client.get(SESSIONS_URL).status_code, 403)

    def test_student_is_denied(self):
        self.login(self.s1.user)
        self.assertEqual(self.client.get(SESSIONS_URL).status_code, 403)
        self.assertEqual(
            self.put_attendance(
                self.session_w2.session_id,
                [{"student_id": self.s1.student_id, "status": "출석"}],
            ).status_code,
            403,
        )

    def test_assistant_without_video_grant_feature_is_denied(self):
        # 조교 프리셋에 영상지급관리는 없다(features.ROLE_PRESETS) — 키 분리
        self.login(self.assistant)
        self.assertEqual(self.post_makeup({}).status_code, 403)

    def test_admin_and_owner_are_allowed(self):
        for user in (self.admin, self.owner):
            self.login(user)
            self.assertEqual(self.client.get(SESSIONS_URL).status_code, 200)
            self.assertEqual(
                self.client.get(self.detail_url(self.session_w2.session_id)).status_code, 200
            )

    def test_assistant_preset_covers_attendance_entry(self):
        # 조교 프리셋에 출결입력이 있다 — 반별 관리가 조교의 일이다(FLOW §3)
        self.login(self.assistant)
        self.assertEqual(self.client.get(SESSIONS_URL).status_code, 200)
        self.assertEqual(
            self.client.get(self.detail_url(self.session_w2.session_id)).status_code, 200
        )

    def test_assistant_with_feature_revoked_is_denied(self):
        # 프리셋 ⊕ delta — 대표가 개별 회수하면 조교도 못 연다
        StaffFeatureGrant.objects.create(
            user=self.assistant, feature_key=FeatureKey.ATTENDANCE_ENTRY, is_granted=False
        )
        self.login(self.assistant)
        self.assertEqual(self.client.get(SESSIONS_URL).status_code, 403)
        self.assertEqual(
            self.client.get(self.detail_url(self.session_w2.session_id)).status_code, 403
        )

    def test_makeup_requires_video_grant_feature(self):
        # 출결입력만 delta 로 받은 조교는 동보(영상지급관리) 불가 — 키 분리 검증
        StaffFeatureGrant.objects.create(
            user=self.assistant, feature_key=FeatureKey.ATTENDANCE_ENTRY, is_granted=True
        )
        self.login(self.assistant)
        self.assertEqual(self.post_makeup({}).status_code, 403)


class SessionListTests(AttendanceAdminFixtureMixin, TestCase):
    """GET /api/admin/attendance/sessions — 회차 목록(강좌·날짜·주차)."""

    def setUp(self):
        self.login(self.admin)

    def test_lists_sessions_with_course_and_week(self):
        res = self.client.get(SESSIONS_URL)
        self.assertEqual(res.status_code, 200)
        sessions = res.json()["sessions"]
        self.assertEqual(
            [s["session_id"] for s in sessions],
            [
                self.session_w1.session_id,
                self.session_w2.session_id,
                self.session_noweek.session_id,
            ],
        )
        w2 = sessions[1]
        self.assertEqual(w2["session_date"], "2026-07-22")
        self.assertEqual(w2["session_no"], 2)
        self.assertEqual(w2["week_no"], 2)
        self.assertEqual(w2["course"], {"course_id": self.course.course_id, "name": "로직엔제"})
        # 주차 미매핑 회차는 강좌·주차가 비어 있다
        self.assertIsNone(sessions[2]["week_no"])
        self.assertIsNone(sessions[2]["course"])

    def test_filters_by_course_id(self):
        res = self.client.get(SESSIONS_URL, {"course_id": self.course.course_id})
        ids = [s["session_id"] for s in res.json()["sessions"]]
        self.assertEqual(ids, [self.session_w1.session_id, self.session_w2.session_id])

    def test_filters_by_date(self):
        res = self.client.get(SESSIONS_URL, {"date": "2026-07-22"})
        ids = [s["session_id"] for s in res.json()["sessions"]]
        self.assertEqual(ids, [self.session_w2.session_id])

    def test_invalid_filters_are_rejected(self):
        self.assertEqual(self.client.get(SESSIONS_URL, {"date": "22/07/2026"}).status_code, 400)
        self.assertEqual(self.client.get(SESSIONS_URL, {"course_id": "abc"}).status_code, 400)

    def test_list_query_count_is_fixed(self):
        with self.assertNumQueries(4):  # 세션인증 2 + 기능키 1 + 회차 1
            self.client.get(SESSIONS_URL)


class SessionDetailTests(AttendanceAdminFixtureMixin, TestCase):
    """GET /sessions/{id} — 명단(퇴원생 포함·표시만) + 기존 출결 + 집계."""

    def setUp(self):
        self.login(self.admin)

    def test_roster_keeps_withdrawn_students_as_display_only_rows(self):
        # 2026-07-29: 퇴원생을 명단에서 빼지 않는다 — 담임 화면에서 5종처럼
        # 보이게 하려면 그 행이 남아 `퇴원` 으로 떠야 한다(출결 값은 4종 유지).
        res = self.client.get(self.detail_url(self.session_w2.session_id))
        self.assertEqual(res.status_code, 200)
        body = res.json()
        ids = [s["student_id"] for s in body["students"]]
        self.assertEqual(
            ids,
            [
                self.s1.student_id,
                self.s2.student_id,
                self.s3.student_id,
                self.s_withdrawn.student_id,
            ],
        )  # 타강좌만 제외
        by_id = {s["student_id"]: s for s in body["students"]}
        self.assertTrue(by_id[self.s_withdrawn.student_id]["is_withdrawn"])
        self.assertEqual(by_id[self.s_withdrawn.student_id]["enrollment_status"], "퇴원")
        self.assertFalse(by_id[self.s1.student_id]["is_withdrawn"])
        self.assertEqual(body["session"]["week_no"], 2)

    def test_existing_attendance_values_and_summary(self):
        Attendance.objects.create(
            session=self.session_w2, student=self.s1, status="출석", exam_taken=True
        )
        Attendance.objects.create(session=self.session_w2, student=self.s2, status="결석")
        res = self.client.get(self.detail_url(self.session_w2.session_id))
        body = res.json()
        by_id = {s["student_id"]: s for s in body["students"]}
        self.assertEqual(by_id[self.s1.student_id]["attendance"]["status"], "출석")
        self.assertTrue(by_id[self.s1.student_id]["attendance"]["exam_taken"])
        self.assertIsNone(by_id[self.s1.student_id]["attendance"]["updated_at"])
        self.assertEqual(by_id[self.s2.student_id]["attendance"]["status"], "결석")
        self.assertIsNone(by_id[self.s3.student_id]["attendance"])
        # 집계는 **입력 대상**만 센다 — 퇴원생을 미입력에 넣으면 "아직 1명 남았다"는
        # 거짓 신호가 되므로 별도 칸으로 빼고 total 에서도 제외한다.
        self.assertEqual(
            body["summary"],
            {
                "출석": 1,
                "결석": 1,
                "결석(동보)": 0,
                "결석(현보)": 0,
                "미입력": 1,
                "퇴원": 1,
                "total": 3,
            },
        )

    def test_roster_rows_carry_attendance_id_for_makeup_grant(self):
        # 즉시 동보 지급(POST /api/admin/attendance/makeup)의 body 키 —
        # 명단 행에서 바로 지급하려면 기존 출결의 PK 가 응답에 있어야 한다
        absent = Attendance.objects.create(
            session=self.session_w2, student=self.s1, status="결석"
        )
        res = self.client.get(self.detail_url(self.session_w2.session_id))
        by_id = {s["student_id"]: s for s in res.json()["students"]}
        self.assertEqual(by_id[self.s1.student_id]["attendance_id"], absent.id)
        # 미입력 학생은 null(키는 존재 — 프런트 분기 단순화)
        self.assertIsNone(by_id[self.s2.student_id]["attendance_id"])

    def test_missing_session_is_404(self):
        self.assertEqual(self.client.get(self.detail_url(99999)).status_code, 404)

    def test_detail_query_count_is_fixed(self):
        Attendance.objects.create(session=self.session_w2, student=self.s1, status="출석")
        with self.assertNumQueries(6):  # 세션인증 2 + 기능키 1 + 회차 1 + 명단 1 + 출결 1
            self.client.get(self.detail_url(self.session_w2.session_id))


class AttendanceUpsertTests(AttendanceAdminFixtureMixin, TestCase):
    """PUT /sessions/{id} — SSOT upsert + 파생 트리거(같은 트랜잭션)."""

    def setUp(self):
        self.login(self.admin)

    # --- 기본 upsert -----------------------------------------------------

    def test_creates_attendance_rows_with_marked_by(self):
        res = self.put_attendance(
            self.session_w2.session_id,
            [
                {"student_id": self.s1.student_id, "status": "출석", "exam_taken": True},
                {"student_id": self.s2.student_id, "status": "결석"},
            ],
        )
        self.assertEqual(res.status_code, 200)
        att = Attendance.objects.get(session=self.session_w2, student=self.s1)
        self.assertEqual(att.status, "출석")
        self.assertTrue(att.exam_taken)
        self.assertEqual(att.marked_by, self.admin)
        self.assertIsNone(att.updated_at)  # 최초 입력은 정정 아님(모델 계약)
        body = res.json()
        self.assertEqual(
            body["summary"],
            {
                "출석": 1,
                "결석": 1,
                "결석(동보)": 0,
                "결석(현보)": 0,
                "미입력": 1,
                "퇴원": 1,
                "total": 3,
            },
        )
        by_id = {s["student_id"]: s for s in body["students"]}
        self.assertEqual(by_id[self.s2.student_id]["attendance"]["status"], "결석")

    def test_partial_upsert_keeps_other_rows(self):
        self.put_attendance(
            self.session_w2.session_id, [{"student_id": self.s1.student_id, "status": "출석"}]
        )
        self.put_attendance(
            self.session_w2.session_id,
            [{"student_id": self.s2.student_id, "status": "결석(현보)"}],
        )
        self.assertEqual(
            Attendance.objects.get(session=self.session_w2, student=self.s1).status, "출석"
        )
        self.assertEqual(
            Attendance.objects.get(session=self.session_w2, student=self.s2).status,
            "결석(현보)",
        )

    def test_correction_sets_updated_at_app_layer(self):
        self.put_attendance(
            self.session_w2.session_id, [{"student_id": self.s1.student_id, "status": "출석"}]
        )
        later = NOW + datetime.timedelta(hours=1)
        self.put_attendance(
            self.session_w2.session_id,
            [{"student_id": self.s1.student_id, "status": "결석"}],
            at=later,
        )
        att = Attendance.objects.get(session=self.session_w2, student=self.s1)
        self.assertEqual(att.status, "결석")
        self.assertEqual(att.updated_at, later)  # 정정 시각 = 앱 레이어 주입(auto_now 아님)

    def test_unchanged_resubmit_does_not_mark_correction(self):
        self.put_attendance(
            self.session_w2.session_id,
            [{"student_id": self.s1.student_id, "status": "출석", "exam_taken": True}],
        )
        self.put_attendance(
            self.session_w2.session_id,
            [{"student_id": self.s1.student_id, "status": "출석", "exam_taken": True}],
            at=NOW + datetime.timedelta(hours=1),
        )
        att = Attendance.objects.get(session=self.session_w2, student=self.s1)
        self.assertIsNone(att.updated_at)

    def test_exam_taken_correction(self):
        self.put_attendance(
            self.session_w2.session_id,
            [{"student_id": self.s1.student_id, "status": "출석", "exam_taken": False}],
        )
        later = NOW + datetime.timedelta(hours=1)
        self.put_attendance(
            self.session_w2.session_id,
            [{"student_id": self.s1.student_id, "status": "출석", "exam_taken": True}],
            at=later,
        )
        att = Attendance.objects.get(session=self.session_w2, student=self.s1)
        self.assertTrue(att.exam_taken)
        self.assertEqual(att.updated_at, later)

    # --- 입력 검증 -------------------------------------------------------

    def test_rejects_student_outside_roster(self):
        res = self.put_attendance(
            self.session_w2.session_id,
            [
                {"student_id": self.s1.student_id, "status": "출석"},
                {"student_id": self.s_other.student_id, "status": "출석"},
            ],
        )
        self.assertEqual(res.status_code, 400)
        # 검증 실패 시 아무것도 저장되지 않는다(원자성)
        self.assertEqual(Attendance.objects.filter(session=self.session_w2).count(), 0)
        self.assertEqual(VideoGrant.objects.count(), 0)

    def test_rejects_entry_for_withdrawn_student(self):
        # 퇴원생은 명단에 **보이지만** 입력 대상이 아니다 — 출결 레코드를
        # 만들지 않는다(퇴원은 students.enrollment_status 단일 원천).
        res = self.put_attendance(
            self.session_w2.session_id,
            [
                {"student_id": self.s1.student_id, "status": "출석"},
                {"student_id": self.s_withdrawn.student_id, "status": "출석"},
            ],
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("퇴원", res.json()["detail"])
        self.assertEqual(Attendance.objects.filter(session=self.session_w2).count(), 0)

    def test_rejects_invalid_status_and_body_shape(self):
        cases = [
            [{"student_id": self.s1.student_id, "status": "퇴원"}],  # 값집합 밖(모델 계약)
            [{"student_id": self.s1.student_id, "status": "지각"}],  # 2026-07-29 제거된 값
            [{"student_id": self.s1.student_id}],  # status 누락
            [{"status": "출석"}],  # student_id 누락
            {"student_id": self.s1.student_id, "status": "출석"},  # 리스트 아님
            [
                {"student_id": self.s1.student_id, "status": "출석"},
                {"student_id": self.s1.student_id, "status": "결석"},  # 중복 학생
            ],
        ]
        for body in cases:
            res = self.put_attendance(self.session_w2.session_id, body)
            self.assertEqual(res.status_code, 400, body)
        self.assertEqual(Attendance.objects.count(), 0)

    def test_session_without_week_mapping_is_rejected(self):
        # 명단은 주차→강좌에서 산정된다 — 미매핑 회차는 입력 불가(400)
        res = self.put_attendance(
            self.session_noweek.session_id,
            [{"student_id": self.s1.student_id, "status": "출석"}],
        )
        self.assertEqual(res.status_code, 400)

    def test_missing_session_is_404(self):
        res = self.put_attendance(
            99999, [{"student_id": self.s1.student_id, "status": "출석"}]
        )
        self.assertEqual(res.status_code, 404)

    # --- 트리거 ① 출석 → 복습영상 자동지급 -------------------------------

    def test_present_creates_auto_video_grant(self):
        self.put_attendance(
            self.session_w2.session_id, [{"student_id": self.s1.student_id, "status": "출석"}]
        )
        att = Attendance.objects.get(session=self.session_w2, student=self.s1)
        grants = VideoGrant.objects.filter(attendance=att).order_by("video__sequence_no")
        # 지급 단위 = 영상 1개 — 그 회차 주차의 `공개` 영상마다 1행
        self.assertEqual([g.video_id for g in grants], self.w2_video_ids())
        for grant in grants:
            self.assertEqual(grant.source, VideoGrant.Source.ATTENDANCE_AUTO)
            self.assertEqual(grant.student_id, self.s1.student_id)
            self.assertEqual(grant.granted_at, NOW)
            self.assertEqual(grant.expires_at, NOW + GRANT_DURATION)
            self.assertEqual(grant.granted_by, self.admin)
            self.assertIsNone(grant.revoked_at)

    def test_grant_covers_only_published_videos_of_that_week(self):
        """지급은 출결 확정 시점에 `공개` 인 그 회차 주차 영상에만 난다(지급 시점 계약).

        준비중 영상에 권한을 미리 깔면 학생이 아직 못 볼 영상의 만료가 조용히
        흘러간다 — 늦게 공개한 영상은 수동 지급으로 메운다(VideoGrant 모델 계약).
        """
        self.put_attendance(
            self.session_w2.session_id, [{"student_id": self.s1.student_id, "status": "출석"}]
        )
        self.assertFalse(VideoGrant.objects.filter(video=self.w2_preparing).exists())
        self.assertFalse(VideoGrant.objects.filter(video=self.w1_video).exists())

    def test_present_resubmit_does_not_duplicate_grant(self):
        entries = [{"student_id": self.s1.student_id, "status": "출석"}]
        self.put_attendance(self.session_w2.session_id, entries)
        self.put_attendance(
            self.session_w2.session_id, entries, at=NOW + datetime.timedelta(hours=2)
        )
        att = Attendance.objects.get(session=self.session_w2, student=self.s1)
        grants = VideoGrant.objects.filter(attendance=att)
        self.assertEqual(grants.count(), len(self.w2_videos))  # 영상당 1행 — 늘지 않는다
        # 재저장이 만료를 연장하지 않는다(최초 지급 유지)
        self.assertEqual({g.expires_at for g in grants}, {NOW + GRANT_DURATION})

    def test_onsite_makeup_absence_grants_review_video_without_counseling(self):
        """`결석(현보)` = 다른 회차에서 그 주 수업을 **실제로 들은** 결석.

        자동지급의 근거는 "그 주 수업을 들었다"이지 출결 라벨 자체가 아니다 —
        영상 보강(동보)조차 "출석생과 동일한 그 주 복습영상 권한"을 받는데
        (PRD 3.2.3) 현장에서 들은 학생을 빼면 앞뒤가 맞지 않는다.
        상담 대기열은 없다 — 보강이 이미 끝났으므로 전화할 사유가 없다.
        """
        self.put_attendance(
            self.session_w2.session_id,
            [{"student_id": self.s1.student_id, "status": "결석(현보)"}],
        )
        att = Attendance.objects.get(session=self.session_w2, student=self.s1)
        grants = VideoGrant.objects.filter(attendance=att).order_by("video__sequence_no")
        self.assertEqual([g.video_id for g in grants], self.w2_video_ids())
        for grant in grants:
            self.assertEqual(grant.source, VideoGrant.Source.ATTENDANCE_AUTO)
            self.assertEqual(grant.expires_at, NOW + GRANT_DURATION)
        self.assertEqual(AbsenceCounseling.objects.count(), 0)
        self.assertEqual(MakeupGrant.objects.count(), 0)

    def test_makeup_absence_grants_makeup_chain_without_counseling(self):
        """`결석(동보)` 는 담임이 찍는 순간 동보 지급까지 확정된다(입구 단일화)."""
        self.put_attendance(
            self.session_w2.session_id,
            [{"student_id": self.s1.student_id, "status": "결석(동보)"}],
        )
        att = Attendance.objects.get(session=self.session_w2, student=self.s1)
        makeup = MakeupGrant.objects.get(attendance=att)
        self.assertEqual(makeup.source, MakeupGrant.Source.ADMIN_CHECK)
        self.assertEqual(makeup.status, MakeupGrant.Status.GRANTED)
        self.assertEqual(makeup.granted_at, NOW)
        grants = VideoGrant.objects.filter(makeup=makeup).order_by("video__sequence_no")
        # 출석생과 동일한 그 주 복습영상 권한(PRD 3.2.3) — 공개 영상마다 1행
        self.assertEqual([g.video_id for g in grants], self.w2_video_ids())
        for grant in grants:
            self.assertEqual(grant.source, VideoGrant.Source.MAKEUP)
            self.assertEqual(grant.expires_at, NOW + GRANT_DURATION)
        # 보강 방법이 확정된 결석이므로 상담 대기열에 올리지 않는다
        self.assertEqual(AbsenceCounseling.objects.count(), 0)
        # 출석 근거 지급은 없다 — 동보는 makeup 근거로만 매달린다
        self.assertFalse(VideoGrant.objects.filter(attendance=att).exists())

    def test_makeup_absence_resubmit_is_idempotent(self):
        entries = [{"student_id": self.s1.student_id, "status": "결석(동보)"}]
        self.put_attendance(self.session_w2.session_id, entries)
        self.put_attendance(
            self.session_w2.session_id, entries, at=NOW + datetime.timedelta(hours=2)
        )
        att = Attendance.objects.get(session=self.session_w2, student=self.s1)
        self.assertEqual(MakeupGrant.objects.filter(attendance=att).count(), 1)
        grants = VideoGrant.objects.filter(makeup__attendance=att)
        self.assertEqual(grants.count(), len(self.w2_videos))  # 영상당 1행 — 늘지 않는다
        self.assertEqual({g.expires_at for g in grants}, {NOW + GRANT_DURATION})

    def test_makeup_absence_absorbs_pending_student_request(self):
        """학생이 이미 신청해 둔 결석을 담임이 `결석(동보)` 로 찍으면 그 신청이 승인된다.

        새 MakeupGrant 를 따로 만들면 학생 신청이 영원히 `신청` 으로 남아
        "동보로 찍혔는데 신청은 안 된" 상태가 된다 — 겹치는 두 흐름을 한
        레코드로 합치는 지점이다.
        """
        self.put_attendance(
            self.session_w2.session_id, [{"student_id": self.s1.student_id, "status": "결석"}]
        )
        att = Attendance.objects.get(session=self.session_w2, student=self.s1)
        pending = MakeupGrant.objects.create(
            student=self.s1,
            attendance=att,
            source=MakeupGrant.Source.STUDENT_REQUEST,
            requested_by=self.s1.user,
        )
        later = NOW + datetime.timedelta(hours=1)
        self.put_attendance(
            self.session_w2.session_id,
            [{"student_id": self.s1.student_id, "status": "결석(동보)"}],
            at=later,
        )
        self.assertEqual(MakeupGrant.objects.filter(attendance=att).count(), 1)
        pending.refresh_from_db()
        self.assertEqual(pending.status, MakeupGrant.Status.GRANTED)
        self.assertEqual(pending.source, MakeupGrant.Source.STUDENT_REQUEST)  # 이력 보존
        grants = VideoGrant.objects.filter(makeup=pending)
        self.assertEqual(grants.count(), len(self.w2_videos))
        self.assertEqual({g.granted_at for g in grants}, {later})

    def test_pending_request_is_granted_when_absence_is_confirmed(self):
        """미리 신청해 둔 결석이 출결표 저장으로 확정되면 **그때** 지급된다(FLOW 3-4).

        지급 조건은 신청 + 결석 확인 둘이고 순서는 상관없다. 승인 단계가
        없으므로 결석이 확정되는 이 자리가 곧 지급 시점이다.
        """
        att = Attendance.objects.create(
            session=self.session_w2, student=self.s1, status=Attendance.Status.PRESENT
        )
        pending = MakeupGrant.objects.create(
            student=self.s1,
            attendance=att,
            source=MakeupGrant.Source.STUDENT_REQUEST,
            requested_by=self.s1.user,
        )
        self.assertFalse(VideoGrant.objects.filter(makeup=pending).exists())

        self.put_attendance(
            self.session_w2.session_id, [{"student_id": self.s1.student_id, "status": "결석"}]
        )

        pending.refresh_from_db()
        self.assertEqual(pending.status, MakeupGrant.Status.GRANTED)
        self.assertEqual(pending.granted_at, NOW)
        self.assertEqual(pending.source, MakeupGrant.Source.STUDENT_REQUEST)  # 이력 보존
        grants = VideoGrant.objects.filter(makeup=pending).order_by("video__sequence_no")
        self.assertEqual([g.video_id for g in grants], self.w2_video_ids())
        self.assertEqual({g.expires_at for g in grants}, {NOW + GRANT_DURATION})
        # 출결도 `결석(동보)` 로 올라간다 — 지급됐는데 `결석` 인 갈린 상태를 안 남긴다
        att.refresh_from_db()
        self.assertEqual(att.status, Attendance.Status.ABSENT_MAKEUP)
        # 보강 방법이 확정됐으므로 상담 대기열에도 올리지 않는다
        self.assertEqual(AbsenceCounseling.objects.filter(attendance=att).count(), 0)
        # 결석이므로 출석 근거 자동지급은 회수된 채로 남는다
        self.assertFalse(
            VideoGrant.objects.filter(attendance=att, revoked_at__isnull=True).exists()
        )

    def test_absence_without_request_grants_nothing(self):
        """신청이 없으면 결석만으로는 안 나간다 — 조건 둘 중 하나가 비었다."""
        self.put_attendance(
            self.session_w2.session_id, [{"student_id": self.s1.student_id, "status": "결석"}]
        )
        att = Attendance.objects.get(session=self.session_w2, student=self.s1)
        self.assertEqual(att.status, Attendance.Status.ABSENT)
        self.assertFalse(MakeupGrant.objects.filter(attendance=att).exists())
        self.assertFalse(VideoGrant.objects.filter(attendance=att).exists())
        self.assertEqual(AbsenceCounseling.objects.filter(attendance=att).count(), 1)

    def test_rejected_request_is_not_granted_by_absence(self):
        """거절된 신청은 살아있는 신청이 아니다 — 결석이 확정돼도 나가지 않는다."""
        att = Attendance.objects.create(
            session=self.session_w2, student=self.s1, status=Attendance.Status.PRESENT
        )
        rejected = MakeupGrant.objects.create(
            student=self.s1,
            attendance=att,
            source=MakeupGrant.Source.STUDENT_REQUEST,
            requested_by=self.s1.user,
            status=MakeupGrant.Status.REJECTED,
        )
        self.put_attendance(
            self.session_w2.session_id, [{"student_id": self.s1.student_id, "status": "결석"}]
        )
        rejected.refresh_from_db()
        self.assertEqual(rejected.status, MakeupGrant.Status.REJECTED)
        self.assertFalse(VideoGrant.objects.filter(makeup=rejected).exists())
        att.refresh_from_db()
        self.assertEqual(att.status, Attendance.Status.ABSENT)

    def test_absent_to_makeup_absence_removes_untouched_counseling(self):
        self.put_attendance(
            self.session_w2.session_id, [{"student_id": self.s2.student_id, "status": "결석"}]
        )
        att = Attendance.objects.get(session=self.session_w2, student=self.s2)
        self.assertEqual(AbsenceCounseling.objects.filter(attendance=att).count(), 1)
        self.put_attendance(
            self.session_w2.session_id,
            [{"student_id": self.s2.student_id, "status": "결석(동보)"}],
            at=NOW + datetime.timedelta(hours=1),
        )
        self.assertEqual(AbsenceCounseling.objects.filter(attendance=att).count(), 0)

    def test_makeup_absence_to_present_revokes_makeup_grant(self):
        self.put_attendance(
            self.session_w2.session_id,
            [{"student_id": self.s1.student_id, "status": "결석(동보)"}],
        )
        later = NOW + datetime.timedelta(hours=1)
        self.put_attendance(
            self.session_w2.session_id,
            [{"student_id": self.s1.student_id, "status": "출석"}],
            at=later,
        )
        att = Attendance.objects.get(session=self.session_w2, student=self.s1)
        makeup_grants = VideoGrant.objects.filter(makeup__attendance=att)
        # 동보 지급은 **전부** 회수된다 — 영상 단위가 된 뒤로 한 동보가 여러 행을 낳으므로
        # 하나만 끄면 학생에게 나머지 영상이 그대로 열려 있다
        self.assertEqual(makeup_grants.count(), len(self.w2_videos))
        for grant in makeup_grants:
            self.assertEqual(grant.revoked_at, later)
            self.assertNotIn(grant, VideoGrant.objects.active(at=later))
        # 출석 자동지급은 새로 난다 — 영상당 1행
        self.assertEqual(
            VideoGrant.objects.filter(attendance=att).count(), len(self.w2_videos)
        )

    def test_makeup_absence_reentry_reactivates_revoked_grant(self):
        self.put_attendance(
            self.session_w2.session_id,
            [{"student_id": self.s1.student_id, "status": "결석(동보)"}],
        )
        self.put_attendance(
            self.session_w2.session_id,
            [{"student_id": self.s1.student_id, "status": "출석"}],
            at=NOW + datetime.timedelta(hours=1),
        )
        t2 = NOW + datetime.timedelta(hours=2)
        self.put_attendance(
            self.session_w2.session_id,
            [{"student_id": self.s1.student_id, "status": "결석(동보)"}],
            at=t2,
        )
        att = Attendance.objects.get(session=self.session_w2, student=self.s1)
        grants = VideoGrant.objects.filter(makeup__attendance=att)
        # 부분 UQ(makeup, video) — 동보 1건 × 영상 1개당 지급 1행(재활성, 행 복제 없음)
        self.assertEqual(grants.count(), len(self.w2_videos))
        for grant in grants:
            self.assertIsNone(grant.revoked_at)
            self.assertEqual(grant.expires_at, t2 + GRANT_DURATION)
        # 출석으로 났던 자동지급은 **전부** 회수된다
        auto_grants = VideoGrant.objects.filter(attendance=att)
        self.assertEqual(auto_grants.count(), len(self.w2_videos))
        for grant in auto_grants:
            self.assertEqual(grant.revoked_at, t2)

    def test_present_to_absent_revokes_auto_grant(self):
        self.put_attendance(
            self.session_w2.session_id, [{"student_id": self.s1.student_id, "status": "출석"}]
        )
        later = NOW + datetime.timedelta(hours=1)
        self.put_attendance(
            self.session_w2.session_id,
            [{"student_id": self.s1.student_id, "status": "결석"}],
            at=later,
        )
        att = Attendance.objects.get(session=self.session_w2, student=self.s1)
        grants = VideoGrant.objects.filter(attendance=att)
        # 그 출결의 자동지급을 **전부** 회수한다(영상당 1행이므로 하나만 끄면 남는다)
        self.assertEqual(grants.count(), len(self.w2_videos))
        for grant in grants:
            self.assertEqual(grant.revoked_at, later)
            self.assertNotIn(grant, VideoGrant.objects.active(at=later))

    def test_absent_back_to_present_reactivates_grant(self):
        self.put_attendance(
            self.session_w2.session_id, [{"student_id": self.s1.student_id, "status": "출석"}]
        )
        t1 = NOW + datetime.timedelta(hours=1)
        self.put_attendance(
            self.session_w2.session_id,
            [{"student_id": self.s1.student_id, "status": "결석"}],
            at=t1,
        )
        t2 = NOW + datetime.timedelta(hours=2)
        self.put_attendance(
            self.session_w2.session_id,
            [{"student_id": self.s1.student_id, "status": "출석"}],
            at=t2,
        )
        att = Attendance.objects.get(session=self.session_w2, student=self.s1)
        grants = VideoGrant.objects.filter(attendance=att)
        # 부분 UQ(attendance, video) — 출석 1건 × 영상 1개당 1행(재활성, 행 복제 없음)
        self.assertEqual(grants.count(), len(self.w2_videos))
        for grant in grants:
            self.assertIsNone(grant.revoked_at)
            self.assertEqual(grant.granted_at, t2)
            self.assertEqual(grant.expires_at, t2 + GRANT_DURATION)

    # --- 트리거 ② 결석 → 상담 대기열 -------------------------------------

    def test_absent_creates_counseling_queue_row(self):
        self.put_attendance(
            self.session_w2.session_id, [{"student_id": self.s2.student_id, "status": "결석"}]
        )
        att = Attendance.objects.get(session=self.session_w2, student=self.s2)
        row = AbsenceCounseling.objects.get(attendance=att)
        self.assertEqual(row.student_id, self.s2.student_id)
        self.assertEqual(row.status, AbsenceCounseling.Status.PENDING)
        self.assertEqual(row.target, AbsenceCounseling.Target.PARENT)  # 1차 = 학부모

    def test_absent_resubmit_does_not_duplicate_queue_row(self):
        entries = [{"student_id": self.s2.student_id, "status": "결석"}]
        self.put_attendance(self.session_w2.session_id, entries)
        self.put_attendance(
            self.session_w2.session_id, entries, at=NOW + datetime.timedelta(hours=1)
        )
        att = Attendance.objects.get(session=self.session_w2, student=self.s2)
        self.assertEqual(AbsenceCounseling.objects.filter(attendance=att).count(), 1)

    def test_absent_to_present_removes_untouched_queue_row(self):
        self.put_attendance(
            self.session_w2.session_id, [{"student_id": self.s2.student_id, "status": "결석"}]
        )
        self.put_attendance(
            self.session_w2.session_id,
            [{"student_id": self.s2.student_id, "status": "출석"}],
            at=NOW + datetime.timedelta(hours=1),
        )
        att = Attendance.objects.get(session=self.session_w2, student=self.s2)
        self.assertEqual(AbsenceCounseling.objects.filter(attendance=att).count(), 0)
        # 정정 후 출석이므로 자동지급은 생성된다 — 영상당 1행
        self.assertEqual(
            VideoGrant.objects.filter(attendance=att).count(), len(self.w2_videos)
        )

    def test_absent_to_present_keeps_touched_counseling_row(self):
        self.put_attendance(
            self.session_w2.session_id, [{"student_id": self.s2.student_id, "status": "결석"}]
        )
        att = Attendance.objects.get(session=self.session_w2, student=self.s2)
        row = AbsenceCounseling.objects.get(attendance=att)
        # 담당자가 이미 통화를 남긴 행 — 감사 이력이므로 보존돼야 한다
        row.status = AbsenceCounseling.Status.COMPLETED
        row.called_at = NOW + datetime.timedelta(minutes=30)
        row.save()
        self.put_attendance(
            self.session_w2.session_id,
            [{"student_id": self.s2.student_id, "status": "출석"}],
            at=NOW + datetime.timedelta(hours=1),
        )
        self.assertEqual(AbsenceCounseling.objects.filter(attendance=att).count(), 1)

    # --- 응답·효율 -------------------------------------------------------

    def test_put_response_contains_triggers_block(self):
        res = self.put_attendance(
            self.session_w2.session_id,
            [
                {"student_id": self.s1.student_id, "status": "출석"},
                {"student_id": self.s2.student_id, "status": "결석"},
            ],
        )
        self.assertEqual(
            res.json()["triggers"],
            {
                # 출석 1명 × 그 회차 주차의 공개 영상 수(권한 = 학생이 체감하는 단위)
                "video_grants_created": len(self.w2_videos),
                "video_grants_revoked": 0,
                "video_grants_reactivated": 0,
                "counselings_created": 1,
                "counselings_removed": 0,
                "makeups_granted": 0,
            },
        )

    def test_put_response_counts_makeup_absence_triggers(self):
        res = self.put_attendance(
            self.session_w2.session_id,
            [
                {"student_id": self.s1.student_id, "status": "결석(동보)"},
                {"student_id": self.s2.student_id, "status": "결석(현보)"},
            ],
        )
        self.assertEqual(
            res.json()["triggers"],
            {
                # 동보 1명(makeup 근거) + 현보 1명(출결 근거) — 각각 영상당 1행
                "video_grants_created": 2 * len(self.w2_videos),
                "video_grants_revoked": 0,
                "video_grants_reactivated": 0,
                "counselings_created": 0,
                "counselings_removed": 0,
                "makeups_granted": 1,
            },
        )

    def test_put_query_count_is_fixed(self):
        entries = [
            {"student_id": self.s1.student_id, "status": "출석"},
            {"student_id": self.s2.student_id, "status": "결석"},
            {"student_id": self.s3.student_id, "status": "결석(현보)"},
        ]
        # 세션인증 2 + 기능키 1 + 회차 1 + 명단 1 + SAVEPOINT/RELEASE 2
        # + 기존출결 1 + INSERT 3
        # + 트리거① 3: 주차 공개영상 조회 1 + 기존지급 조회 1 + 지급 bulk INSERT 1
        #   (지급 단위가 영상이 된 뒤 영상 조회 1쿼리가 늘고, 대신 건별 INSERT 가
        #    bulk 1쿼리로 묶여 총합은 그대로다 — 학생·영상 수가 늘어도 고정)
        # + 동보조회 1(지급건 없음 → 2번째 쿼리 생략) + 대기열조회/생성 2
        with freeze_now(), self.assertNumQueries(17):
            self.client.put(
                self.detail_url(self.session_w2.session_id),
                data=json.dumps(entries),
                content_type="application/json",
            )


class MakeupCheckTests(AttendanceAdminFixtureMixin, TestCase):
    """POST /api/admin/attendance/makeup — 동보 관리자 체크(지급 체인)."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.absent_att = Attendance.objects.create(
            session=cls.session_w2, student=cls.s2, status="결석"
        )
        cls.present_att = Attendance.objects.create(
            session=cls.session_w2, student=cls.s1, status="출석"
        )

    def setUp(self):
        self.login(self.admin)

    def _body(self, att=None, student=None):
        att = att or self.absent_att
        student = student or self.s2
        return {"student_id": student.student_id, "attendance_id": att.id}

    def test_makeup_promotes_attendance_to_makeup_absence(self):
        """관리자 체크 = 출결을 `결석(동보)` 로 올리는 것과 같다(입구 단일화).

        출결은 `결석` 인데 동보만 지급된 상태를 남기지 않는다 — 그러면 출결
        SSOT 만 보고는 이 학생이 동보인지 알 수 없다.
        """
        self.post_makeup(self._body())
        self.absent_att.refresh_from_db()
        self.assertEqual(self.absent_att.status, Attendance.Status.ABSENT_MAKEUP)
        self.assertEqual(self.absent_att.updated_at, NOW)

    def test_makeup_removes_untouched_counseling_row(self):
        row = AbsenceCounseling.objects.create(
            student=self.s2,
            attendance=self.absent_att,
            target=AbsenceCounseling.Target.PARENT,
            status=AbsenceCounseling.Status.PENDING,
        )
        self.post_makeup(self._body())
        self.assertFalse(AbsenceCounseling.objects.filter(pk=row.counsel_id).exists())

    def test_makeup_creates_grant_chain(self):
        res = self.post_makeup(self._body())
        self.assertEqual(res.status_code, 201)
        makeup = MakeupGrant.objects.get(attendance=self.absent_att)
        self.assertEqual(makeup.source, MakeupGrant.Source.ADMIN_CHECK)
        self.assertEqual(makeup.status, MakeupGrant.Status.GRANTED)
        self.assertEqual(makeup.granted_at, NOW)
        self.assertEqual(makeup.requested_by, self.admin)
        grants = list(
            VideoGrant.objects.filter(makeup=makeup).order_by("video__sequence_no")
        )
        self.assertEqual([g.video_id for g in grants], self.w2_video_ids())
        for grant in grants:
            self.assertEqual(grant.source, VideoGrant.Source.MAKEUP)
            self.assertEqual(grant.student_id, self.s2.student_id)
            self.assertEqual(grant.granted_at, NOW)
            self.assertEqual(grant.expires_at, NOW + GRANT_DURATION)
        body = res.json()
        self.assertEqual(body["makeup"]["makeup_id"], makeup.makeup_id)
        # 응답은 만든 행 **전부**를 싣는다 — 하나만 실으면 몇 개 지급됐는지가 사라진다
        self.assertEqual(
            [g["grant_id"] for g in body["video_grants"]], [g.grant_id for g in grants]
        )

    def test_makeup_on_non_absent_attendance_is_400(self):
        res = self.post_makeup(self._body(att=self.present_att, student=self.s1))
        self.assertEqual(res.status_code, 400)
        self.assertEqual(MakeupGrant.objects.count(), 0)
        self.assertEqual(VideoGrant.objects.count(), 0)

    def test_makeup_student_mismatch_is_400(self):
        res = self.post_makeup(self._body(student=self.s3))
        self.assertEqual(res.status_code, 400)
        self.assertEqual(MakeupGrant.objects.count(), 0)

    def test_makeup_missing_attendance_is_404(self):
        res = self.post_makeup({"student_id": self.s2.student_id, "attendance_id": 99999})
        self.assertEqual(res.status_code, 404)

    def test_makeup_invalid_body_is_400(self):
        for body in ({}, {"student_id": self.s2.student_id}, {"attendance_id": "abc"}):
            self.assertEqual(self.post_makeup(body).status_code, 400)

    def test_duplicate_makeup_is_400(self):
        self.post_makeup(self._body())
        res = self.post_makeup(self._body(), at=NOW + datetime.timedelta(hours=1))
        self.assertEqual(res.status_code, 400)
        self.assertEqual(MakeupGrant.objects.filter(attendance=self.absent_att).count(), 1)
        self.assertEqual(
            VideoGrant.objects.filter(makeup__attendance=self.absent_att).count(),
            len(self.w2_videos),
        )

    def test_makeup_on_session_without_week_is_400(self):
        att = Attendance.objects.create(
            session=self.session_noweek, student=self.s2, status="결석"
        )
        res = self.post_makeup(self._body(att=att))
        self.assertEqual(res.status_code, 400)
        self.assertEqual(MakeupGrant.objects.count(), 0)


class WithdrawTests(AttendanceAdminFixtureMixin, TestCase):
    """POST /api/admin/attendance/withdraw — 출결 화면에서 퇴원 처리 (PRD 3.1.6).

    출결 값집합에 `퇴원` 을 넣지 않기로 한 대가다 — 담임이 명단에서 바로
    퇴원을 찍을 수 있어야 화면이 5종처럼 보인다. 한 번 처리하면 이후 회차
    명단에는 자동으로 퇴원 행으로 뜬다(생애주기 상태이므로 회차와 무관).
    """

    def setUp(self):
        self.login(self.admin)

    def test_withdraw_sets_enrollment_status_and_audit_fields(self):
        res = self.post_withdraw(
            {"student_id": self.s1.student_id, "reason": "타 학원 이동"}
        )
        self.assertEqual(res.status_code, 200)
        self.s1.refresh_from_db()
        self.assertEqual(self.s1.enrollment_status, Student.EnrollmentStatus.WITHDRAWN)
        self.assertEqual(self.s1.withdrawn_at, NOW)
        self.assertEqual(self.s1.withdrawn_by, self.admin)
        self.assertEqual(self.s1.withdrawn_reason, "타 학원 이동")
        self.assertEqual(res.json()["enrollment_status"], "퇴원")

    def test_withdrawn_student_becomes_display_only_row_on_next_session(self):
        self.post_withdraw({"student_id": self.s1.student_id})
        res = self.client.get(self.detail_url(self.session_w2.session_id))
        by_id = {s["student_id"]: s for s in res.json()["students"]}
        self.assertTrue(by_id[self.s1.student_id]["is_withdrawn"])
        self.assertEqual(res.json()["summary"]["퇴원"], 2)
        self.assertEqual(res.json()["summary"]["total"], 2)

    def test_withdraw_does_not_create_attendance_rows(self):
        self.post_withdraw({"student_id": self.s1.student_id})
        self.assertEqual(Attendance.objects.count(), 0)

    def test_withdraw_is_idempotent(self):
        self.post_withdraw({"student_id": self.s_withdrawn.student_id})
        res = self.post_withdraw({"student_id": self.s_withdrawn.student_id})
        self.assertEqual(res.status_code, 200)
        self.s_withdrawn.refresh_from_db()
        self.assertEqual(
            self.s_withdrawn.enrollment_status, Student.EnrollmentStatus.WITHDRAWN
        )

    def test_withdraw_missing_student_is_404(self):
        self.assertEqual(self.post_withdraw({"student_id": 99999}).status_code, 404)

    def test_withdraw_invalid_body_is_400(self):
        for body in ({}, {"student_id": "abc"}, {"student_id": True}):
            self.assertEqual(self.post_withdraw(body).status_code, 400)

    def test_withdraw_requires_attendance_entry_feature(self):
        self.client.logout()
        # 조교 프리셋에는 출결입력이 있다 — 게이트를 보려면 delta 로 회수해야 한다
        StaffFeatureGrant.objects.create(
            user=self.assistant, feature_key=FeatureKey.ATTENDANCE_ENTRY, is_granted=False
        )
        self.login(self.assistant)
        self.assertEqual(
            self.post_withdraw({"student_id": self.s1.student_id}).status_code, 403
        )

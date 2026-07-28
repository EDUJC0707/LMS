"""출결 입력 API 3차 슬라이스 테스트 — SSOT 쓰기 + 파생 트리거 (PRD 3.1.6·3.1.4①·3.2.3).

검증 축:
- 기능 키 게이트: 출결 조회/입력 = 출결입력, 동보 = 영상지급관리 (프리셋 ⊕ delta)
- 회차 목록/상세: 강좌·주차·날짜, 명단(수강생만·퇴원 제외), 기존 출결 값, 집계
- SSOT 쓰기: 부분/전체 upsert, 정정 시 updated_at 앱 레이어 갱신(auto_now 아님)
- 파생 트리거(동기·같은 트랜잭션):
  ① 출석 → VideoGrant(출석자동, 그 회차 주차, +7일) / 정정 시 revoke·재활성
  ② 결석 → AbsenceCounseling 대기열 / 정정 시 미통화 대기 행만 정리
- 동보 체인: MakeupGrant(관리자체크, 지급완료) + VideoGrant(동보), 비결석 400
- 쿼리 효율: assertNumQueries 고정(N+1 회귀 방지)

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
from apps.videos.models import MakeupGrant, VideoGrant

from .models import Attendance, ClassSession

PASSWORD = "pw-Secret-77!"
SESSIONS_URL = "/api/admin/attendance/sessions"
MAKEUP_URL = "/api/admin/attendance/makeup"

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
        user=user, unique_id=f"uid-{login_id}", enrollment_status=status
    )


class AttendanceAdminFixtureMixin:
    """로직엔제 강좌 축소판 — 수강생 3 + 퇴원 1 + 타강좌 1, 회차 2개(주차 매핑)."""

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

    def test_assistant_without_feature_is_denied(self):
        # 조교 프리셋에는 출결입력·영상지급관리가 없다(features.ROLE_PRESETS)
        self.login(self.assistant)
        self.assertEqual(self.client.get(SESSIONS_URL).status_code, 403)
        self.assertEqual(
            self.client.get(self.detail_url(self.session_w2.session_id)).status_code, 403
        )
        self.assertEqual(self.post_makeup({}).status_code, 403)

    def test_admin_and_owner_are_allowed(self):
        for user in (self.admin, self.owner):
            self.login(user)
            self.assertEqual(self.client.get(SESSIONS_URL).status_code, 200)
            self.assertEqual(
                self.client.get(self.detail_url(self.session_w2.session_id)).status_code, 200
            )

    def test_assistant_with_delta_grant_is_allowed(self):
        # 프리셋 ⊕ delta — 대표가 개별 부여하면 조교도 출결입력 가능
        StaffFeatureGrant.objects.create(
            user=self.assistant, feature_key=FeatureKey.ATTENDANCE_ENTRY, is_granted=True
        )
        self.login(self.assistant)
        self.assertEqual(self.client.get(SESSIONS_URL).status_code, 200)

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
    """GET /sessions/{id} — 명단(수강생만·퇴원 제외) + 기존 출결 + 집계."""

    def setUp(self):
        self.login(self.admin)

    def test_roster_is_enrolled_students_excluding_withdrawn(self):
        res = self.client.get(self.detail_url(self.session_w2.session_id))
        self.assertEqual(res.status_code, 200)
        body = res.json()
        ids = [s["student_id"] for s in body["students"]]
        self.assertEqual(
            ids, [self.s1.student_id, self.s2.student_id, self.s3.student_id]
        )  # 퇴원·타강좌 제외
        names = [s["name"] for s in body["students"]]
        self.assertEqual(names, ["김서연", "이준호", "박민지"])
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
        self.assertEqual(
            body["summary"], {"출석": 1, "결석": 1, "지각": 0, "미입력": 1, "total": 3}
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
            body["summary"], {"출석": 1, "결석": 1, "지각": 0, "미입력": 1, "total": 3}
        )
        by_id = {s["student_id"]: s for s in body["students"]}
        self.assertEqual(by_id[self.s2.student_id]["attendance"]["status"], "결석")

    def test_partial_upsert_keeps_other_rows(self):
        self.put_attendance(
            self.session_w2.session_id, [{"student_id": self.s1.student_id, "status": "출석"}]
        )
        self.put_attendance(
            self.session_w2.session_id, [{"student_id": self.s2.student_id, "status": "지각"}]
        )
        self.assertEqual(
            Attendance.objects.get(session=self.session_w2, student=self.s1).status, "출석"
        )
        self.assertEqual(
            Attendance.objects.get(session=self.session_w2, student=self.s2).status, "지각"
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
        for bad in (self.s_withdrawn, self.s_other):
            res = self.put_attendance(
                self.session_w2.session_id,
                [
                    {"student_id": self.s1.student_id, "status": "출석"},
                    {"student_id": bad.student_id, "status": "출석"},
                ],
            )
            self.assertEqual(res.status_code, 400)
        # 검증 실패 시 아무것도 저장되지 않는다(원자성)
        self.assertEqual(Attendance.objects.filter(session=self.session_w2).count(), 0)
        self.assertEqual(VideoGrant.objects.count(), 0)

    def test_rejects_invalid_status_and_body_shape(self):
        cases = [
            [{"student_id": self.s1.student_id, "status": "퇴원"}],  # 값집합 밖(모델 계약)
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
        grant = VideoGrant.objects.get(attendance=att)
        self.assertEqual(grant.source, VideoGrant.Source.ATTENDANCE_AUTO)
        self.assertEqual(grant.student_id, self.s1.student_id)
        self.assertEqual(grant.course_week_id, self.week2.week_id)
        self.assertEqual(grant.granted_at, NOW)
        self.assertEqual(grant.expires_at, NOW + GRANT_DURATION)
        self.assertEqual(grant.granted_by, self.admin)
        self.assertIsNone(grant.revoked_at)

    def test_present_resubmit_does_not_duplicate_grant(self):
        entries = [{"student_id": self.s1.student_id, "status": "출석"}]
        self.put_attendance(self.session_w2.session_id, entries)
        self.put_attendance(
            self.session_w2.session_id, entries, at=NOW + datetime.timedelta(hours=2)
        )
        att = Attendance.objects.get(session=self.session_w2, student=self.s1)
        grants = VideoGrant.objects.filter(attendance=att)
        self.assertEqual(grants.count(), 1)
        # 재저장이 만료를 연장하지 않는다(최초 지급 유지)
        self.assertEqual(grants[0].expires_at, NOW + GRANT_DURATION)

    def test_late_does_not_create_grant_or_counseling(self):
        # 자동지급은 '출석' 확정만(PRD 3.1.4 ①) — 지각은 지급·상담 대기열 모두 없음
        self.put_attendance(
            self.session_w2.session_id, [{"student_id": self.s1.student_id, "status": "지각"}]
        )
        self.assertEqual(VideoGrant.objects.count(), 0)
        self.assertEqual(AbsenceCounseling.objects.count(), 0)

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
        grant = VideoGrant.objects.get(attendance=att)
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
        self.assertEqual(grants.count(), 1)  # 부분 UQ — 출석 1건당 1행(재활성, 행 복제 없음)
        grant = grants[0]
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
        # 정정 후 출석이므로 자동지급은 생성된다
        self.assertEqual(VideoGrant.objects.filter(attendance=att).count(), 1)

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
                "video_grants_created": 1,
                "video_grants_revoked": 0,
                "video_grants_reactivated": 0,
                "counselings_created": 1,
                "counselings_removed": 0,
            },
        )

    def test_put_query_count_is_fixed(self):
        entries = [
            {"student_id": self.s1.student_id, "status": "출석"},
            {"student_id": self.s2.student_id, "status": "결석"},
            {"student_id": self.s3.student_id, "status": "지각"},
        ]
        # 세션인증 2 + 기능키 1 + 회차 1 + 명단 1 + SAVEPOINT/RELEASE 2
        # + 기존출결 1 + INSERT 3 + 지급조회/생성 2 + 대기열조회/생성 2 = 15
        with freeze_now(), self.assertNumQueries(15):
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

    def test_makeup_creates_grant_chain(self):
        res = self.post_makeup(self._body())
        self.assertEqual(res.status_code, 201)
        makeup = MakeupGrant.objects.get(attendance=self.absent_att)
        self.assertEqual(makeup.source, MakeupGrant.Source.ADMIN_CHECK)
        self.assertEqual(makeup.status, MakeupGrant.Status.GRANTED)
        self.assertEqual(makeup.granted_at, NOW)
        self.assertEqual(makeup.requested_by, self.admin)
        grant = VideoGrant.objects.get(makeup=makeup)
        self.assertEqual(grant.source, VideoGrant.Source.MAKEUP)
        self.assertEqual(grant.student_id, self.s2.student_id)
        self.assertEqual(grant.course_week_id, self.week2.week_id)
        self.assertEqual(grant.granted_at, NOW)
        self.assertEqual(grant.expires_at, NOW + GRANT_DURATION)
        body = res.json()
        self.assertEqual(body["makeup"]["makeup_id"], makeup.makeup_id)
        self.assertEqual(body["video_grant"]["grant_id"], grant.grant_id)

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
        self.assertEqual(VideoGrant.objects.filter(makeup__attendance=self.absent_att).count(), 1)

    def test_makeup_on_session_without_week_is_400(self):
        att = Attendance.objects.create(
            session=self.session_noweek, student=self.s2, status="결석"
        )
        res = self.post_makeup(self._body(att=att))
        self.assertEqual(res.status_code, 400)
        self.assertEqual(MakeupGrant.objects.count(), 0)

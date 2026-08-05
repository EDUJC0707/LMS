"""동보 신청 API 4차 슬라이스 테스트 — 예비 경로(전화 두절) (PRD 3.2.3·§4).

검증 축:
- 역할 게이트: 학생/학부모 신청, 관리자 목록·승인·거절(기능 키 = 영상지급관리)
- 자격(§4): 본인(자녀)의 `결석` 출결만 신청 가능 — 타인 404(존재 비노출),
  비결석 400. 자격 없으면 API 자체가 4xx
- 중복: 같은 결석에 신청/승인/지급완료 존재 시 400, 거절만 재신청 허용
- 승인 체인: 지급완료 전환 + VideoGrant(동보) 생성 — 3차 슬라이스
  grant_makeup 과 같은 공용 서비스(apps.videos.makeup) 경유.
  지급 단위는 **영상 1개**라 그 주차 `공개` 영상마다 1행이다(2026-08-04)
- 시간: 승인 시각은 apps.videos.views.timezone.now 를 patch 해 고정
  (Asia/Seoul — attendance_admin 테스트 선례)
"""
import datetime
import json
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from apps.accounts.features import FeatureKey
from apps.accounts.models import Parent, ParentStudent, StaffFeatureGrant, Student, User
from apps.boards.models import AbsenceCounseling
from apps.curriculum.models import Course, CourseWeek
from apps.grades.models import Attendance, ClassSession

from .models import MakeupGrant, Video, VideoGrant

PASSWORD = "pw-Secret-77!"
STUDENT_URL = "/api/student/makeup-request"
PARENT_URL = "/api/parent/makeup-request"
ADMIN_LIST_URL = "/api/admin/makeup-requests"

# 기준 시각: 2026-07-22(수) 22:00 KST
NOW = timezone.make_aware(datetime.datetime(2026, 7, 22, 22, 0))
GRANT_DURATION = datetime.timedelta(days=7)


def freeze_now(at=NOW):
    """동보 뷰의 기준 시각 고정(뷰 모듈 경유 timezone.now 만 patch)."""
    return mock.patch("apps.videos.views.timezone.now", return_value=at)


def make_user(login_id, role, name="사용자"):
    return User.objects.create_user(login_id=login_id, password=PASSWORD, name=name, role=role)


def make_student(login_id, name):
    user = make_user(login_id, User.Role.STUDENT, name=name)
    return Student.objects.create(
        user=user, matching_key=f"uid-{login_id}",
        enrollment_status=Student.EnrollmentStatus.REGISTERED,
    )


def make_parent(login_id, name, *children):
    user = make_user(login_id, User.Role.PARENT, name=name)
    parent = Parent.objects.create(user=user, name=name, phone=f"010-{login_id}")
    for child in children:
        ParentStudent.objects.create(parent=parent, student=child)
    return parent


class MakeupFixtureMixin:
    """결석 s1(주차 매핑 O/X)·s2(타 가족) + 학부모 2명 + 직원 3역할 + 1주차 영상."""

    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user("owner-1", User.Role.OWNER, name="대표")
        cls.admin = make_user("admin-1", User.Role.ADMIN, name="관리자")
        cls.assistant = make_user("assist-1", User.Role.ASSISTANT, name="조교")

        cls.course = Course.objects.create(name="로직엔제")
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
        cls.session_noweek = ClassSession.objects.create(
            session_date=datetime.date(2026, 7, 29), session_no=3
        )

        # 지급 대상은 그 주차의 `공개` 영상들이다 — 1주차만 영상을 깐다.
        # 2주차는 영상 없음(공개 영상이 0개인 주차의 승인 경로용).
        cls.w1_video1 = Video.objects.create(
            course_week=cls.week1, title="1주차 1강",
            status=Video.Status.PUBLISHED, sequence_no=1,
        )
        cls.w1_video2 = Video.objects.create(
            course_week=cls.week1, title="1주차 2강",
            status=Video.Status.PUBLISHED, sequence_no=2,
        )
        cls.w1_video_preparing = Video.objects.create(
            course_week=cls.week1, title="1주차 3강(준비중)",
            status=Video.Status.PREPARING, sequence_no=3,
        )
        cls.week1_videos = [cls.w1_video1, cls.w1_video2]  # sequence_no 순 = 지급 순

        cls.s1 = make_student("stu-1", "김서연")
        cls.s2 = make_student("stu-2", "이준호")
        cls.p1 = make_parent("par-1", "김학부", cls.s1)
        cls.p2 = make_parent("par-2", "이학부", cls.s2)

        cls.att_s1_absent = Attendance.objects.create(
            session=cls.session_w1, student=cls.s1, status=Attendance.Status.ABSENT
        )
        cls.att_s1_present = Attendance.objects.create(
            session=cls.session_w2, student=cls.s1, status=Attendance.Status.PRESENT
        )
        cls.att_s1_noweek = Attendance.objects.create(
            session=cls.session_noweek, student=cls.s1, status=Attendance.Status.ABSENT
        )
        cls.att_s2_absent = Attendance.objects.create(
            session=cls.session_w1, student=cls.s2, status=Attendance.Status.ABSENT
        )

    def login(self, user):
        self.client.force_login(user)

    def post_json(self, url, body):
        return self.client.post(url, data=json.dumps(body), content_type="application/json")

    def request_makeup(self, url, attendance):
        return self.post_json(url, {"attendance_id": attendance.id})

    def make_request_row(self, attendance, student=None, source=MakeupGrant.Source.STUDENT_REQUEST,
                         status=MakeupGrant.Status.REQUESTED):
        student = student if student is not None else attendance.student
        return MakeupGrant.objects.create(
            student=student, attendance=attendance, source=source, status=status,
            requested_by=student.user,
        )

    def approve_url(self, makeup_id):
        return f"{ADMIN_LIST_URL}/{makeup_id}/approve"

    def reject_url(self, makeup_id):
        return f"{ADMIN_LIST_URL}/{makeup_id}/reject"


class MakeupAccessTests(MakeupFixtureMixin, TestCase):
    """역할 게이트 + 기능 키(영상지급관리) 게이트."""

    def test_anonymous_is_denied(self):
        self.assertEqual(self.post_json(STUDENT_URL, {}).status_code, 403)
        self.assertEqual(self.post_json(PARENT_URL, {}).status_code, 403)
        self.assertEqual(self.client.get(ADMIN_LIST_URL).status_code, 403)

    def test_role_gates_between_consumer_endpoints(self):
        self.login(self.p1.user)
        self.assertEqual(self.request_makeup(STUDENT_URL, self.att_s1_absent).status_code, 403)
        self.login(self.s1.user)
        self.assertEqual(self.request_makeup(PARENT_URL, self.att_s1_absent).status_code, 403)
        self.assertEqual(self.client.get(ADMIN_LIST_URL).status_code, 403)

    def test_admin_list_feature_gate(self):
        self.login(self.assistant)  # 조교 프리셋에 영상지급관리 없음
        self.assertEqual(self.client.get(ADMIN_LIST_URL).status_code, 403)
        StaffFeatureGrant.objects.create(
            user=self.assistant, feature_key=FeatureKey.VIDEO_GRANT_ADMIN, is_granted=True
        )
        self.assertEqual(self.client.get(ADMIN_LIST_URL).status_code, 200)
        self.login(self.admin)
        self.assertEqual(self.client.get(ADMIN_LIST_URL).status_code, 200)
        self.login(self.owner)
        self.assertEqual(self.client.get(ADMIN_LIST_URL).status_code, 200)

    def test_approve_feature_gate(self):
        makeup = self.make_request_row(self.att_s1_absent)
        self.login(self.assistant)
        self.assertEqual(self.post_json(self.approve_url(makeup.makeup_id), {}).status_code, 403)
        self.login(self.s1.user)
        self.assertEqual(self.post_json(self.approve_url(makeup.makeup_id), {}).status_code, 403)


class StudentMakeupRequestTests(MakeupFixtureMixin, TestCase):
    """POST /api/student/makeup-request — 본인 결석만, 중복 400."""

    def setUp(self):
        self.login(self.s1.user)

    def test_request_creates_makeup(self):
        res = self.request_makeup(STUDENT_URL, self.att_s1_absent)
        self.assertEqual(res.status_code, 201)
        makeup = MakeupGrant.objects.get(attendance=self.att_s1_absent)
        self.assertEqual(makeup.student_id, self.s1.student_id)
        self.assertEqual(makeup.source, MakeupGrant.Source.STUDENT_REQUEST)
        self.assertEqual(makeup.status, MakeupGrant.Status.REQUESTED)
        self.assertEqual(makeup.requested_by_id, self.s1.user.user_id)
        body = res.json()["makeup"]
        self.assertEqual(body["makeup_id"], makeup.makeup_id)
        self.assertEqual(body["attendance_id"], self.att_s1_absent.id)
        self.assertEqual(body["source"], "학생신청")
        self.assertEqual(body["status"], "신청")
        self.assertEqual(body["session_date"], "2026-07-15")
        self.assertEqual(body["week_no"], 1)
        self.assertEqual(body["course_name"], "로직엔제")
        # 신청만으로는 지급되지 않는다 — 승인 시점에 VideoGrant 생성
        self.assertFalse(VideoGrant.objects.filter(makeup=makeup).exists())

    def test_request_invalid_attendance_id_400(self):
        for body in ({}, {"attendance_id": "abc"}, {"attendance_id": True}, [1]):
            res = self.post_json(STUDENT_URL, body)
            self.assertEqual(res.status_code, 400, body)

    def test_request_other_students_attendance_404(self):
        res = self.request_makeup(STUDENT_URL, self.att_s2_absent)
        self.assertEqual(res.status_code, 404)
        self.assertFalse(MakeupGrant.objects.exists())

    def test_request_unknown_attendance_404(self):
        res = self.post_json(STUDENT_URL, {"attendance_id": 999999})
        self.assertEqual(res.status_code, 404)

    def test_request_non_absent_attendance_400(self):
        # §4: 결석이 없으면(출석 출결) 신청 API 자체가 4xx
        res = self.request_makeup(STUDENT_URL, self.att_s1_present)
        self.assertEqual(res.status_code, 400)
        self.assertFalse(MakeupGrant.objects.exists())

    def test_request_duplicate_active_400(self):
        for dup_status in (
            MakeupGrant.Status.REQUESTED,
            MakeupGrant.Status.APPROVED,
            MakeupGrant.Status.GRANTED,
        ):
            MakeupGrant.objects.all().delete()
            self.make_request_row(self.att_s1_absent, status=dup_status)
            res = self.request_makeup(STUDENT_URL, self.att_s1_absent)
            self.assertEqual(res.status_code, 400, dup_status)
            self.assertEqual(MakeupGrant.objects.count(), 1)

    def test_request_after_rejection_allows_again(self):
        self.make_request_row(self.att_s1_absent, status=MakeupGrant.Status.REJECTED)
        res = self.request_makeup(STUDENT_URL, self.att_s1_absent)
        self.assertEqual(res.status_code, 201)
        self.assertEqual(MakeupGrant.objects.filter(attendance=self.att_s1_absent).count(), 2)

    def test_request_unmapped_week_still_allowed(self):
        # 주차 미매핑은 관리자가 고칠 데이터 문제 — 신청은 받고 승인에서 차단
        res = self.request_makeup(STUDENT_URL, self.att_s1_noweek)
        self.assertEqual(res.status_code, 201)
        body = res.json()["makeup"]
        self.assertIsNone(body["week_no"])


class ParentMakeupRequestTests(MakeupFixtureMixin, TestCase):
    """POST /api/parent/makeup-request — 자녀 소유 검증(2차 슬라이스 404 패턴)."""

    def setUp(self):
        self.login(self.p1.user)

    def test_parent_request_creates_makeup(self):
        res = self.request_makeup(PARENT_URL, self.att_s1_absent)
        self.assertEqual(res.status_code, 201)
        makeup = MakeupGrant.objects.get(attendance=self.att_s1_absent)
        self.assertEqual(makeup.student_id, self.s1.student_id)
        self.assertEqual(makeup.source, MakeupGrant.Source.PARENT_REQUEST)
        self.assertEqual(makeup.status, MakeupGrant.Status.REQUESTED)
        self.assertEqual(makeup.requested_by_id, self.p1.user.user_id)
        self.assertEqual(res.json()["makeup"]["source"], "학부모신청")

    def test_parent_cannot_request_for_unowned_child_404(self):
        res = self.request_makeup(PARENT_URL, self.att_s2_absent)
        self.assertEqual(res.status_code, 404)
        self.assertFalse(MakeupGrant.objects.exists())

    def test_parent_invalid_body_400(self):
        self.assertEqual(self.post_json(PARENT_URL, {}).status_code, 400)

    def test_parent_non_absent_attendance_400(self):
        res = self.request_makeup(PARENT_URL, self.att_s1_present)
        self.assertEqual(res.status_code, 400)

    def test_parent_duplicate_active_400(self):
        self.make_request_row(self.att_s1_absent)  # 학생 경로 선신청
        res = self.request_makeup(PARENT_URL, self.att_s1_absent)
        self.assertEqual(res.status_code, 400)


class AdminMakeupListTests(MakeupFixtureMixin, TestCase):
    """GET /api/admin/makeup-requests?status= — 신청 목록(영상지급관리)."""

    def setUp(self):
        self.login(self.admin)
        self.requested = self.make_request_row(self.att_s1_absent)
        self.granted = self.make_request_row(
            self.att_s2_absent, source=MakeupGrant.Source.ADMIN_CHECK,
            status=MakeupGrant.Status.GRANTED,
        )

    def test_list_returns_all_requests(self):
        res = self.client.get(ADMIN_LIST_URL)
        self.assertEqual(res.status_code, 200)
        rows = res.json()["requests"]
        self.assertEqual(len(rows), 2)
        first = rows[0]  # makeup_id 오름차순
        self.assertEqual(first["makeup_id"], self.requested.makeup_id)
        self.assertEqual(first["student"]["name"], "김서연")
        self.assertEqual(first["student"]["student_id"], self.s1.student_id)
        self.assertEqual(first["source"], "학생신청")
        self.assertEqual(first["status"], "신청")
        self.assertEqual(first["session_date"], "2026-07-15")
        self.assertEqual(first["week_no"], 1)
        self.assertEqual(first["requested_by"], "김서연")

    def test_list_filters_by_status(self):
        res = self.client.get(ADMIN_LIST_URL, {"status": "신청"})
        rows = res.json()["requests"]
        self.assertEqual([r["makeup_id"] for r in rows], [self.requested.makeup_id])
        res = self.client.get(ADMIN_LIST_URL, {"status": "지급완료"})
        rows = res.json()["requests"]
        self.assertEqual([r["makeup_id"] for r in rows], [self.granted.makeup_id])

    def test_list_invalid_status_400(self):
        self.assertEqual(self.client.get(ADMIN_LIST_URL, {"status": "이상한값"}).status_code, 400)


class AdminMakeupApproveRejectTests(MakeupFixtureMixin, TestCase):
    """approve = 지급완료 + VideoGrant(동보) 체인 / reject = 거절 전환."""

    def setUp(self):
        self.login(self.admin)
        self.makeup = self.make_request_row(self.att_s1_absent)

    def approve(self, makeup_id, at=NOW):
        with freeze_now(at):
            return self.post_json(self.approve_url(makeup_id), {})

    def test_approve_grants_video(self):
        res = self.approve(self.makeup.makeup_id)
        self.assertEqual(res.status_code, 200)
        self.makeup.refresh_from_db()
        self.assertEqual(self.makeup.status, MakeupGrant.Status.GRANTED)
        self.assertEqual(self.makeup.granted_at, NOW)
        grants = list(VideoGrant.objects.filter(makeup=self.makeup).order_by("grant_id"))
        # 지급 단위가 영상 1개다 — 결석 회차 주차의 `공개` 영상마다 1행(2026-08-04)
        self.assertEqual(len(grants), len(self.week1_videos))
        self.assertEqual(
            [g.video_id for g in grants], [v.video_id for v in self.week1_videos]
        )
        for grant in grants:
            self.assertEqual(grant.student_id, self.s1.student_id)
            self.assertEqual(grant.source, VideoGrant.Source.MAKEUP)
            self.assertEqual(grant.granted_by_id, self.admin.user_id)
            self.assertEqual(grant.granted_at, NOW)
            self.assertEqual(grant.expires_at, NOW + GRANT_DURATION)
        body = res.json()
        self.assertEqual(body["makeup"]["status"], "지급완료")
        self.assertEqual(
            [row["grant_id"] for row in body["video_grants"]], [g.grant_id for g in grants]
        )
        self.assertEqual(
            [row["video_id"] for row in body["video_grants"]],
            [v.video_id for v in self.week1_videos],
        )

    def test_approve_skips_unpublished_video(self):
        """`공개` 가 아닌 영상에는 권한이 생기지 않는다 — 지급 시점 계약(VideoGrant).

        아직 못 볼 영상에 권한을 미리 깔면 만료만 조용히 흘러간다.
        """
        self.approve(self.makeup.makeup_id)
        granted_video_ids = set(
            VideoGrant.objects.filter(makeup=self.makeup).values_list("video_id", flat=True)
        )
        self.assertNotIn(self.w1_video_preparing.video_id, granted_video_ids)

    def test_approve_without_published_video_still_completes(self):
        """공개 영상이 0개인 주차 — 권한은 0건이어도 신청은 `지급완료` 로 끝난다.

        지급 처리가 끝난 것과 볼 영상이 아직 없는 것은 별개 사실이라 뭉치지 않는다.
        """
        attendance = Attendance.objects.create(  # 2주차 = 영상 없는 주차
            session=self.session_w2, student=self.s2, status=Attendance.Status.ABSENT
        )
        makeup = self.make_request_row(attendance)
        res = self.approve(makeup.makeup_id)
        self.assertEqual(res.status_code, 200)
        makeup.refresh_from_db()
        self.assertEqual(makeup.status, MakeupGrant.Status.GRANTED)
        self.assertEqual(makeup.granted_at, NOW)
        self.assertFalse(VideoGrant.objects.filter(makeup=makeup).exists())
        self.assertEqual(res.json()["video_grants"], [])

    def test_approve_promotes_attendance_to_makeup_absence(self):
        """승인도 출결을 `결석(동보)` 로 올린다 — 입구 셋의 끝 상태 단일화.

        지급은 났는데 출결은 `결석` 이면 출결 SSOT 만 보고는 이 학생이 동보인지
        알 수 없고, 담임이 그 결석을 다시 상담 대기열에서 만나게 된다.
        """
        self.approve(self.makeup.makeup_id)
        self.att_s1_absent.refresh_from_db()
        self.assertEqual(self.att_s1_absent.status, Attendance.Status.ABSENT_MAKEUP)
        self.assertEqual(self.att_s1_absent.updated_at, NOW)

    def test_approve_removes_untouched_counseling_row(self):
        row = AbsenceCounseling.objects.create(
            student=self.s1,
            attendance=self.att_s1_absent,
            target=AbsenceCounseling.Target.PARENT,
            status=AbsenceCounseling.Status.PENDING,
        )
        self.approve(self.makeup.makeup_id)
        self.assertFalse(AbsenceCounseling.objects.filter(pk=row.counsel_id).exists())

    def test_approve_unknown_404(self):
        self.assertEqual(self.approve(999999).status_code, 404)

    def test_approve_twice_400(self):
        self.approve(self.makeup.makeup_id)
        res = self.approve(self.makeup.makeup_id)
        self.assertEqual(res.status_code, 400)
        # 재승인이 튕겼으므로 첫 승인분(영상마다 1행)만 남는다
        self.assertEqual(
            VideoGrant.objects.filter(makeup=self.makeup).count(), len(self.week1_videos)
        )

    def test_approve_rejected_400(self):
        self.makeup.status = MakeupGrant.Status.REJECTED
        self.makeup.save(update_fields=["status"])
        self.assertEqual(self.approve(self.makeup.makeup_id).status_code, 400)

    def test_approve_when_attendance_corrected_400(self):
        # 정정으로 결석이 아니게 된 경우 — 출석자동 지급과 이중 지급 차단
        self.att_s1_absent.status = Attendance.Status.PRESENT
        self.att_s1_absent.save(update_fields=["status"])
        self.assertEqual(self.approve(self.makeup.makeup_id).status_code, 400)
        self.assertFalse(VideoGrant.objects.filter(makeup=self.makeup).exists())

    def test_approve_without_attendance_400(self):
        self.makeup.attendance = None
        self.makeup.save(update_fields=["attendance"])
        self.assertEqual(self.approve(self.makeup.makeup_id).status_code, 400)

    def test_approve_unmapped_week_400(self):
        makeup = self.make_request_row(self.att_s1_noweek)
        self.assertEqual(self.approve(makeup.makeup_id).status_code, 400)

    def test_approve_when_admin_check_already_granted_400(self):
        # 같은 결석에 관리자체크 지급이 선행된 경우 — 이중 지급 차단
        self.make_request_row(
            self.att_s1_absent, source=MakeupGrant.Source.ADMIN_CHECK,
            status=MakeupGrant.Status.GRANTED,
        )
        self.assertEqual(self.approve(self.makeup.makeup_id).status_code, 400)

    def test_reject_transitions_and_blocks_reprocess(self):
        res = self.post_json(self.reject_url(self.makeup.makeup_id), {})
        self.assertEqual(res.status_code, 200)
        self.makeup.refresh_from_db()
        self.assertEqual(self.makeup.status, MakeupGrant.Status.REJECTED)
        self.assertIsNone(self.makeup.granted_at)
        self.assertEqual(res.json()["makeup"]["status"], "거절")
        # 거절된 신청은 재처리 불가
        rerejected = self.post_json(self.reject_url(self.makeup.makeup_id), {})
        self.assertEqual(rerejected.status_code, 400)
        self.assertEqual(self.approve(self.makeup.makeup_id).status_code, 400)

    def test_reject_unknown_404(self):
        self.assertEqual(self.post_json(self.reject_url(999999), {}).status_code, 404)

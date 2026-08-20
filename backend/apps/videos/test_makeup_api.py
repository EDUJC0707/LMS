"""동보 신청 API 테스트 (PRD 3.2.3·§4, FLOW 3-4).

검증 축:
- 역할 게이트: 학생/학부모 신청, 관리자 목록·거절(기능 키 = 영상지급관리)
- 자격(§4): 본인(자녀)의 `결석` 출결만 신청 가능 — 타인 404(존재 비노출),
  비결석 400. 자격 없으면 API 자체가 4xx
- 중복: 같은 결석에 신청/지급완료 존재 시 400, 거절만 재신청 허용
- **승인이 없다**(FLOW 3-4): 결석이 이미 확정된 신청은 받는 자리에서 바로
  `지급완료` + VideoGrant(동보) 까지 간다. 지급 단위는 **영상 1개**라 그 주차
  `공개` 영상마다 1행이다(2026-08-04). 신청이 먼저인 쪽(미리 신청 → 나중에
  결석 확정)은 출결 트리거가 낸다 — grades.test_attendance_admin_api
- 시간: 지급 시각은 apps.grades.attendance_admin.timezone.now 를 patch 해 고정
  (지급 체인이 그 모듈의 grant_makeup 을 지난다 — Asia/Seoul)
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
    """지급 체인의 기준 시각 고정 — 신청은 attendance_admin.grant_makeup 을 지난다."""
    return mock.patch("apps.grades.attendance_admin.timezone.now", return_value=at)


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


class StudentMakeupRequestTests(MakeupFixtureMixin, TestCase):
    """POST /api/student/makeup-request — 본인 결석만, 중복 400."""

    def setUp(self):
        self.login(self.s1.user)

    def test_request_creates_makeup(self):
        """결석이 이미 확정돼 있으므로 신청받는 자리에서 바로 지급된다(FLOW 3-4)."""
        with freeze_now():
            res = self.request_makeup(STUDENT_URL, self.att_s1_absent)
        self.assertEqual(res.status_code, 201)
        makeup = MakeupGrant.objects.get(attendance=self.att_s1_absent)
        self.assertEqual(makeup.student_id, self.s1.student_id)
        self.assertEqual(makeup.source, MakeupGrant.Source.STUDENT_REQUEST)
        self.assertEqual(makeup.status, MakeupGrant.Status.GRANTED)
        self.assertEqual(makeup.granted_at, NOW)
        self.assertEqual(makeup.requested_by_id, self.s1.user.user_id)
        body = res.json()["makeup"]
        self.assertEqual(body["makeup_id"], makeup.makeup_id)
        self.assertEqual(body["attendance_id"], self.att_s1_absent.id)
        self.assertEqual(body["source"], "학생신청")
        self.assertEqual(body["status"], "지급완료")
        self.assertEqual(body["session_date"], "2026-07-15")
        self.assertEqual(body["week_no"], 1)
        self.assertEqual(body["course_name"], "로직엔제")
        grants = list(VideoGrant.objects.filter(makeup=makeup).order_by("grant_id"))
        self.assertEqual(
            [g.video_id for g in grants], [v.video_id for v in self.week1_videos]
        )
        for grant in grants:
            self.assertEqual(grant.source, VideoGrant.Source.MAKEUP)
            self.assertEqual(grant.granted_at, NOW)
            self.assertEqual(grant.expires_at, NOW + GRANT_DURATION)
            # 승인한 사람이 없다 — 조건이 차서 나간 것이라 처리자가 비어 있다
            self.assertIsNone(grant.granted_by_id)

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
        for dup_status in (MakeupGrant.Status.REQUESTED, MakeupGrant.Status.GRANTED):
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

    def test_request_on_an_unmarked_cell_does_not_touch_the_attendance(self):
        """**신청이 출결 값을 바꾸지 않는다**(FLOW 3-4).

        학생이 눌렀다고 미입력 칸이 `결석(동보)` 가 되면 조교는 그 학생을 "아직
        안 본 칸"에서 못 찾고, `결석` 이 안 찍혀 영상이 영영 안 나간다 — 화면은
        이미 동보라고 말하는데. 신청은 받아 두고 지급은 결석이 찍힐 때 난다.
        """
        attendance = self.att_s1_absent
        attendance.status = Attendance.Status.UNENTERED
        attendance.save(update_fields=["status"])
        res = self.request_makeup(STUDENT_URL, attendance)
        self.assertEqual(res.status_code, 201)
        attendance.refresh_from_db()
        self.assertEqual(attendance.status, Attendance.Status.UNENTERED)
        self.assertIsNone(attendance.updated_at)
        makeup = MakeupGrant.objects.get(attendance=attendance)
        self.assertEqual(makeup.status, MakeupGrant.Status.REQUESTED)
        self.assertFalse(VideoGrant.objects.filter(makeup=makeup).exists())

    def test_request_on_an_onsite_makeup_is_400(self):
        """현보는 그 주 수업을 이미 들었다 — 결석이 아닌 것이 확실한 값이다."""
        self.att_s1_absent.status = Attendance.Status.ABSENT_ONSITE
        self.att_s1_absent.save(update_fields=["status"])
        res = self.request_makeup(STUDENT_URL, self.att_s1_absent)
        self.assertEqual(res.status_code, 400)
        self.assertFalse(MakeupGrant.objects.exists())

    def test_request_unmapped_week_still_allowed(self):
        """주차 미매핑은 관리자가 고칠 데이터 문제 — 신청은 받고 영상만 0건이다.

        지급 처리가 끝난 것과 볼 영상이 아직 없는 것은 별개 사실이라 뭉치지
        않는다(공개 영상이 0개인 주차와 같은 취급).
        """
        res = self.request_makeup(STUDENT_URL, self.att_s1_noweek)
        self.assertEqual(res.status_code, 201)
        body = res.json()["makeup"]
        self.assertIsNone(body["week_no"])
        makeup = MakeupGrant.objects.get(attendance=self.att_s1_noweek)
        self.assertEqual(makeup.status, MakeupGrant.Status.GRANTED)
        self.assertFalse(VideoGrant.objects.filter(makeup=makeup).exists())


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
        self.assertEqual(makeup.status, MakeupGrant.Status.GRANTED)
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


class MakeupGrantOnRequestTests(MakeupFixtureMixin, TestCase):
    """신청 = 지급 (FLOW 3-4) — 승인 단계는 없다. reject 만 관리자에게 남는다."""

    def setUp(self):
        self.login(self.s1.user)

    def request_now(self, attendance, at=NOW):
        with freeze_now(at):
            return self.request_makeup(STUDENT_URL, attendance)

    def test_request_skips_unpublished_video(self):
        """`공개` 가 아닌 영상에는 권한이 생기지 않는다 — 지급 시점 계약(VideoGrant).

        아직 못 볼 영상에 권한을 미리 깔면 만료만 조용히 흘러간다.
        """
        self.request_now(self.att_s1_absent)
        granted_video_ids = set(
            VideoGrant.objects.filter(makeup__attendance=self.att_s1_absent).values_list(
                "video_id", flat=True
            )
        )
        self.assertNotIn(self.w1_video_preparing.video_id, granted_video_ids)

    def test_request_without_published_video_still_completes(self):
        """공개 영상이 0개인 주차 — 권한은 0건이어도 신청은 `지급완료` 로 끝난다."""
        session = ClassSession.objects.create(  # 2주차 = 영상 없는 주차
            session_date=datetime.date(2026, 7, 23), session_no=4, course_week=self.week2
        )
        attendance = Attendance.objects.create(
            session=session, student=self.s1, status=Attendance.Status.ABSENT
        )
        res = self.request_now(attendance)
        self.assertEqual(res.status_code, 201)
        makeup = MakeupGrant.objects.get(attendance=attendance)
        self.assertEqual(makeup.status, MakeupGrant.Status.GRANTED)
        self.assertEqual(makeup.granted_at, NOW)
        self.assertFalse(VideoGrant.objects.filter(makeup=makeup).exists())

    def test_request_promotes_attendance_to_makeup_absence(self):
        """출결도 `결석(동보)` 로 올라간다 — 입구 셋의 끝 상태 단일화.

        지급은 났는데 출결은 `결석` 이면 출결 SSOT 만 보고는 이 학생이 동보인지
        알 수 없고, 담임이 그 결석을 다시 상담 대기열에서 만나게 된다.
        """
        self.request_now(self.att_s1_absent)
        self.att_s1_absent.refresh_from_db()
        self.assertEqual(self.att_s1_absent.status, Attendance.Status.ABSENT_MAKEUP)
        self.assertEqual(self.att_s1_absent.updated_at, NOW)
        # 출결 입력자를 학생 계정으로 덮어쓰지 않는다 — 담임이 찍은 것이 아니다
        self.assertIsNone(self.att_s1_absent.marked_by_id)

    def test_request_removes_untouched_counseling_row(self):
        row = AbsenceCounseling.objects.create(
            student=self.s1,
            attendance=self.att_s1_absent,
            target=AbsenceCounseling.Target.PARENT,
            status=AbsenceCounseling.Status.PENDING,
        )
        self.request_now(self.att_s1_absent)
        self.assertFalse(AbsenceCounseling.objects.filter(pk=row.counsel_id).exists())

    def test_request_twice_400_and_grants_once(self):
        self.request_now(self.att_s1_absent)
        res = self.request_now(self.att_s1_absent, at=NOW + datetime.timedelta(hours=2))
        self.assertEqual(res.status_code, 400)
        self.assertEqual(MakeupGrant.objects.filter(attendance=self.att_s1_absent).count(), 1)
        grants = VideoGrant.objects.filter(makeup__attendance=self.att_s1_absent)
        self.assertEqual(grants.count(), len(self.week1_videos))
        # 두 번째가 튕겼으므로 만료가 뒤로 밀리지 않는다
        self.assertEqual({g.expires_at for g in grants}, {NOW + GRANT_DURATION})

    def test_request_when_admin_check_already_granted_400(self):
        # 같은 결석에 관리자체크 지급이 선행된 경우 — 이중 지급 차단
        self.make_request_row(
            self.att_s1_absent, source=MakeupGrant.Source.ADMIN_CHECK,
            status=MakeupGrant.Status.GRANTED,
        )
        self.assertEqual(self.request_now(self.att_s1_absent).status_code, 400)

    def test_already_held_video_is_not_granted_again(self):
        """이미 가진 영상은 건너뛰고 **만료를 뒤로 밀지 않는다** (FLOW 3-5).

        출석으로 받은 영상을 동보로 또 받게 되는 자리다 — 같은 주차 회차가
        둘이면(보강 회차 등) 한쪽에서 이미 나간 권한이 살아 있다.
        """
        earlier = NOW - datetime.timedelta(days=2)
        held = VideoGrant.objects.create(
            student=self.s1,
            video=self.w1_video1,
            source=VideoGrant.Source.ATTENDANCE_AUTO,
            granted_at=earlier,
            expires_at=earlier + GRANT_DURATION,
        )
        self.request_now(self.att_s1_absent)
        makeup = MakeupGrant.objects.get(attendance=self.att_s1_absent)
        # 아직 없던 2강만 새로 나간다
        self.assertEqual(
            list(VideoGrant.objects.filter(makeup=makeup).values_list("video_id", flat=True)),
            [self.w1_video2.video_id],
        )
        held.refresh_from_db()
        self.assertEqual(held.expires_at, earlier + GRANT_DURATION)
        self.assertEqual(
            VideoGrant.objects.filter(student=self.s1, video=self.w1_video1).count(), 1
        )

    def test_revoked_grant_does_not_block_new_one(self):
        """회수된 권한은 "가진 것"이 아니다 — 지금 볼 수 없으므로 다시 나간다."""
        VideoGrant.objects.create(
            student=self.s1,
            video=self.w1_video1,
            source=VideoGrant.Source.ATTENDANCE_AUTO,
            granted_at=NOW - datetime.timedelta(days=2),
            expires_at=NOW + GRANT_DURATION,
            revoked_at=NOW - datetime.timedelta(days=1),
        )
        self.request_now(self.att_s1_absent)
        makeup = MakeupGrant.objects.get(attendance=self.att_s1_absent)
        self.assertEqual(
            set(VideoGrant.objects.filter(makeup=makeup).values_list("video_id", flat=True)),
            {v.video_id for v in self.week1_videos},
        )

    def test_approve_endpoint_is_gone(self):
        """구 승인 엔드포인트는 존재하지 않는다(FLOW 3-4)."""
        self.login(self.admin)
        makeup = self.make_request_row(self.att_s2_absent)
        res = self.post_json(f"{ADMIN_LIST_URL}/{makeup.makeup_id}/approve", {})
        self.assertEqual(res.status_code, 404)


class AdminMakeupRejectTests(MakeupFixtureMixin, TestCase):
    """reject = 거절 전환 — 결석이 확정되지 않아 `신청` 으로 남은 행을 닫는다."""

    def setUp(self):
        self.login(self.admin)
        self.makeup = self.make_request_row(self.att_s1_absent)

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

    def test_reject_unknown_404(self):
        self.assertEqual(self.post_json(self.reject_url(999999), {}).status_code, 404)

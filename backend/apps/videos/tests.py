"""videos 스모크 테스트 — 도메인 4(영상/동보) 핵심 계약 검증.

설계 근거: docs/db/lms-db-design-2026-07-15.md 도메인 4([전면 개정 2026-07-22]),
PRD 3.1.3(DRM 전환)·3.1.4(출석 자동지급·7일 만료·부여/만료 이력)·3.2.3(동보)·
PRD §4 상태 기반 노출(권한 지급된 영상만 — 지급 단위 개정 2026-08-04).
Provider 중립(payments.Payment 선례)·`active()` 게이팅(curriculum.released() 선례).
"""
import datetime

from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import Student, User
from apps.curriculum.models import Course, CourseWeek
from apps.grades.models import Attendance, ClassSession

from .models import MakeupGrant, Video, VideoGrant


def make_student(matching_key="3_1234"):
    return Student.objects.create(matching_key=matching_key)


def make_week(week_no=1, course=None):
    course = course or Course.objects.create(name="로직엔제")
    return CourseWeek.objects.create(course=course, week_no=week_no)


def make_attendance(student, status="출석"):
    session = ClassSession.objects.create(session_date=datetime.date(2026, 7, 22))
    return Attendance.objects.create(session=session, student=student, status=status)


def make_video(week=None, sequence_no=1):
    # 지급 대상은 `공개` 영상뿐이다(VideoGrant 지급 시점 계약)
    return Video.objects.create(
        course_week=week,
        title=f"{sequence_no}강",
        status=Video.Status.PUBLISHED,
        sequence_no=sequence_no,
    )


def make_grant(student, video, **kwargs):
    now = timezone.now()
    kwargs.setdefault("source", VideoGrant.Source.ATTENDANCE_AUTO)
    kwargs.setdefault("granted_at", now)
    kwargs.setdefault("expires_at", now + datetime.timedelta(days=7))
    return VideoGrant.objects.create(student=student, video=video, **kwargs)


class VideoTests(TestCase):
    def test_table_and_pk_column_follow_design(self):
        self.assertEqual(Video._meta.db_table, "videos")
        self.assertEqual(Video._meta.pk.column, "video_id")

    def test_provider_neutral_nullable_fields(self):
        # 업체(Mux/VdoCipher) 미정 + 연동 후순위(PRD 3.1.3) — provider·external_ref
        # 없이 영상 메타를 먼저 등록할 수 있어야 한다. 주차 무관 특강은 course_week NULL.
        video = Video.objects.create(title="7월 특강")
        self.assertIsNone(video.provider)
        self.assertIsNone(video.external_ref)
        self.assertIsNone(video.course_week)
        self.assertIsNone(video.duration_seconds)
        self.assertIsNone(video.sequence_no)

    def test_status_defaults_to_preparing(self):
        # 안전 기본값은 닫힘(key_considerations §5) — 기본 `준비중`
        video = Video.objects.create(title="1주차 1강")
        self.assertEqual(video.status, Video.Status.PREPARING)
        self.assertEqual(video.status, "준비중")

    def test_provider_value_set(self):
        # Provider 중립: 업체 값집합은 mux/vdocipher(미정 — NULL 허용)
        self.assertEqual(set(Video.Provider.values), {"mux", "vdocipher"})

    def test_status_value_set(self):
        self.assertEqual(set(Video.Status.values), {"준비중", "공개", "아카이브"})

    def test_external_ref_unique_per_provider_when_set(self):
        # 부분 UQ(provider, external_ref) WHERE external_ref IS NOT NULL
        Video.objects.create(title="a", provider=Video.Provider.MUX, external_ref="asset-1")
        with self.assertRaises(IntegrityError):
            Video.objects.create(
                title="b", provider=Video.Provider.MUX, external_ref="asset-1"
            )

    def test_null_external_ref_not_constrained(self):
        # 연동 전(external_ref NULL) 영상 다건 등록 가능 — 부분 UQ 조건 밖
        Video.objects.create(title="a", provider=Video.Provider.MUX)
        Video.objects.create(title="b", provider=Video.Provider.MUX)
        self.assertEqual(Video.objects.count(), 2)


class VideoGrantActiveTests(TestCase):
    """`active()` — 소비자 API 유일 진입 계약(curriculum.released() 선례)."""

    def setUp(self):
        self.student = make_student()
        self.video = make_video(make_week())
        # 기준 시각 고정 — 경계를 결정적으로 검증
        self.at = timezone.make_aware(datetime.datetime(2026, 7, 22, 10, 0))

    def _active_ids(self):
        return set(VideoGrant.objects.active(at=self.at).values_list("grant_id", flat=True))

    def test_unexpired_unrevoked_grant_is_active(self):
        grant = make_grant(
            self.student, self.video,
            granted_at=self.at - datetime.timedelta(days=1),
            expires_at=self.at + datetime.timedelta(days=6),
        )
        self.assertIn(grant.grant_id, self._active_ids())

    def test_expired_grant_is_inactive(self):
        grant = make_grant(
            self.student, self.video,
            granted_at=self.at - datetime.timedelta(days=8),
            expires_at=self.at - datetime.timedelta(days=1),
        )
        self.assertNotIn(grant.grant_id, self._active_ids())

    def test_expiry_boundary_is_inactive(self):
        # expires_at == 기준 시각 → 만료(expires_at > at 만 활성. 만료 시각 도달
        # 즉시 시청 페이지 소멸 — PRD 3.1.4 ⑥)
        grant = make_grant(self.student, self.video, expires_at=self.at)
        self.assertNotIn(grant.grant_id, self._active_ids())

    def test_revoked_grant_is_inactive(self):
        # 수동 회수(PRD 3.1.4 예외 처리) — 만료 전이라도 비활성
        grant = make_grant(
            self.student, self.video,
            expires_at=self.at + datetime.timedelta(days=6),
            revoked_at=self.at - datetime.timedelta(hours=1),
        )
        self.assertNotIn(grant.grant_id, self._active_ids())

    def test_active_defaults_to_now(self):
        now = timezone.now()
        make_grant(
            self.student, self.video,
            granted_at=now, expires_at=now + datetime.timedelta(days=7),
        )
        self.assertEqual(VideoGrant.objects.active().count(), 1)

    def test_active_contract_documented(self):
        # 소비자 API 유일 진입 계약이 docstring 에 명시(released() 선례)
        self.assertIn("유일", VideoGrant.objects.active.__doc__)


class VideoGrantTests(TestCase):
    def setUp(self):
        self.student = make_student()
        self.week = make_week()
        # 한 주차에 영상 2개 — 지급 단위가 영상이라 권한도 영상마다 갈린다
        self.video = make_video(self.week, sequence_no=1)
        self.other_video = make_video(self.week, sequence_no=2)

    def test_table_and_pk_column_follow_design(self):
        self.assertEqual(VideoGrant._meta.db_table, "video_grants")
        self.assertEqual(VideoGrant._meta.pk.column, "grant_id")

    def test_source_value_set(self):
        # 지급 경로: 출석자동(3.1.4 ①)/동보(3.2.3)/학생신청/수동(예외 처리)
        self.assertEqual(
            set(VideoGrant.Source.values), {"출석자동", "동보", "학생신청", "수동"}
        )

    def test_sync_status_null_before_integration(self):
        # DRM 연동 전 NULL 운영(연동 후순위 — PRD 3.1.3)
        grant = make_grant(self.student, self.video)
        self.assertIsNone(grant.sync_status)
        self.assertIsNone(grant.synced_at)
        self.assertEqual(
            set(VideoGrant.SyncStatus.values), {"대기", "부여반영", "회수반영", "실패"}
        )

    def test_grant_unit_is_video_not_course_week(self):
        # 지급 단위 개정(2026-08-04): 권한은 영상 1개에 걸린다. 권한이 course_week
        # 를 들고 있으면 영상과 같은 칸을 공유해, 영상의 주차를 고치는 순간 그 주차
        # 권한이 통째로 끊겼다(실측 51건). 두 축을 다시 붙이지 않는다.
        field_names = {f.name for f in VideoGrant._meta.get_fields()}
        self.assertNotIn("course_week", field_names)
        self.assertFalse(VideoGrant._meta.get_field("video").null)

    def test_attendance_partial_unique(self):
        # 부분 UQ(attendance, video): 출석 1건 + 영상 1개당 자동지급 1건
        attendance = make_attendance(self.student)
        make_grant(self.student, self.video, attendance=attendance)
        with self.assertRaises(IntegrityError):
            make_grant(self.student, self.video, attendance=attendance)

    def test_same_attendance_grants_each_video(self):
        # 한 출석이 그 주 영상 수만큼 행을 낳는다 — attendance 단독 UQ 였다면
        # 두 번째 영상에서 막혔다(2026-08-04 UQ 개정의 요지)
        attendance = make_attendance(self.student)
        videos = [self.video, self.other_video]
        for video in videos:
            make_grant(self.student, video, attendance=attendance)
        self.assertEqual(
            VideoGrant.objects.filter(attendance=attendance).count(), len(videos)
        )

    def test_null_attendance_not_constrained(self):
        # 수동·신청 지급(attendance NULL)은 다건 허용 — 부분 UQ 조건 밖
        make_grant(self.student, self.video, source=VideoGrant.Source.MANUAL)
        make_grant(self.student, self.video, source=VideoGrant.Source.MANUAL)
        self.assertEqual(VideoGrant.objects.count(), 2)

    def test_makeup_partial_unique(self):
        # 부분 UQ(makeup, video): 동보 1건 + 영상 1개당 지급 1건
        makeup = MakeupGrant.objects.create(
            student=self.student, source=MakeupGrant.Source.ADMIN_CHECK
        )
        make_grant(self.student, self.video, source=VideoGrant.Source.MAKEUP, makeup=makeup)
        with self.assertRaises(IntegrityError):
            make_grant(
                self.student, self.video, source=VideoGrant.Source.MAKEUP, makeup=makeup
            )

    def test_same_makeup_grants_each_video(self):
        # 동보도 출석생과 같은 그 주 영상 전부를 연다(PRD 3.2.3) — 영상마다 1행
        makeup = MakeupGrant.objects.create(
            student=self.student, source=MakeupGrant.Source.ADMIN_CHECK
        )
        videos = [self.video, self.other_video]
        for video in videos:
            make_grant(self.student, video, source=VideoGrant.Source.MAKEUP, makeup=makeup)
        self.assertEqual(VideoGrant.objects.filter(makeup=makeup).count(), len(videos))

    def test_student_expiry_index_exists(self):
        # 만료 배치·학생별 활성 권한 조회 축(설계 [전면 개정 2026-07-22])
        index_fields = [idx.fields for idx in VideoGrant._meta.indexes]
        self.assertIn(["student", "expires_at"], index_fields)


class MakeupGrantTests(TestCase):
    def setUp(self):
        self.student = make_student()

    def test_table_and_pk_column_follow_design(self):
        self.assertEqual(MakeupGrant._meta.db_table, "makeup_grants")
        self.assertEqual(MakeupGrant._meta.pk.column, "makeup_id")

    def test_status_defaults_to_requested(self):
        makeup = MakeupGrant.objects.create(
            student=self.student, source=MakeupGrant.Source.STUDENT_REQUEST
        )
        self.assertEqual(makeup.status, MakeupGrant.Status.REQUESTED)
        self.assertEqual(makeup.status, "신청")
        self.assertIsNone(makeup.granted_at)

    def test_source_value_set(self):
        # 관리자체크(상담 후 1차 경로)/학생신청·학부모신청(연락 두절 예비 경로)
        self.assertEqual(
            set(MakeupGrant.Source.values), {"관리자체크", "학생신청", "학부모신청"}
        )

    def test_status_value_set(self):
        self.assertEqual(
            set(MakeupGrant.Status.values), {"신청", "승인", "지급완료", "거절"}
        )

    def test_no_tuition_billable_field(self):
        # 동보 무과금(2026-07-15 확정, 8-8) — is_tuition_billable 은 만들지 않는다
        field_names = {f.name for f in MakeupGrant._meta.get_fields()}
        self.assertNotIn("is_tuition_billable", field_names)

    def test_grant_chain_contract_documented(self):
        # 지급완료 시 VideoGrant(source=동보) 생성 계약이 docstring 에 명시
        self.assertIn("지급완료", MakeupGrant.__doc__)
        self.assertIn("VideoGrant", MakeupGrant.__doc__)

    def test_requested_by_records_parent_or_student_account(self):
        # 동보 신청은 학생 본인·학부모 모두 가능(PRD 3.2.3) — 신청 주체 기록
        parent_user = User.objects.create_user(
            login_id="01011112222", password="pw", name="학부모", role=User.Role.PARENT
        )
        makeup = MakeupGrant.objects.create(
            student=self.student,
            source=MakeupGrant.Source.PARENT_REQUEST,
            requested_by=parent_user,
        )
        self.assertEqual(makeup.requested_by, parent_user)

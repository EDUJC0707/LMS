"""복습영상 재생 API 테스트 — 권한 강제 + 서버 워터마크 (PRD 3.1.3/3.1.4·§4).

GET /api/student/videos/{video_id}/playback

검증 축:
- 권한 원천: `VideoGrant.objects.active()` 단 하나(모델 docstring의 "소비자용 API
  유일 진입" 계약). 만료·회수·타인 권한·다른 영상 권한은 전부 못 본다
- 지급 단위는 **영상 1개**(2026-08-04 개정) — 권한은 영상에 붙어 있으므로
  관리자가 영상의 주차를 옮겨도 이미 지급된 권한은 끊기지 않는다
- 존재 비노출(§4): 권한 밖 video_id 는 상태와 무관하게 404 — 403 으로 갈리면
  "그 번호의 영상은 있다"가 새어 나간다(clinic·grades 성적표 선례와 동일)
- 이중 게이트: `공개` 상태 + 권한. 준비중·아카이브는 권한이 있어도 404
  (Video 모델 docstring 계약)
- 워터마크: 서버가 만든 완성 문자열. 시청 날짜는 **서버 시계 Asia/Seoul** —
  기기 시계를 믿지 않는다. 뷰의 timezone.now 를 갈아 끼워 확인한다
  (동보 API 테스트 freeze_now 선례)
"""
import datetime
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import Parent, Student, User
from apps.curriculum.models import Course, CourseWeek

from .models import Video, VideoGrant

PASSWORD = "pw-Secret-77!"

# 기준 시각: 2026-07-30(목) 22:00 KST
NOW = timezone.make_aware(datetime.datetime(2026, 7, 30, 22, 0))
GRANT_DURATION = datetime.timedelta(days=7)


def freeze_now(at=NOW):
    """재생 뷰의 기준 시각 고정 — 뷰 모듈 경유 timezone.now 만 patch."""
    return mock.patch("apps.videos.views.timezone.now", return_value=at)


def playback_url(video):
    video_id = video.video_id if isinstance(video, Video) else video
    return f"/api/student/videos/{video_id}/playback"


def make_user(login_id, role, name="사용자"):
    return User.objects.create_user(login_id=login_id, password=PASSWORD, name=name, role=role)


def make_student(login_id, name, grade="고2"):
    user = make_user(login_id, User.Role.STUDENT, name=name)
    return Student.objects.create(
        user=user,
        unique_id=f"uid-{login_id}",
        grade=grade,
        enrollment_status=Student.EnrollmentStatus.REGISTERED,
    )


class PlaybackFixtureMixin:
    """1·2주차 영상 + 상태별 영상 + 학생 3명(고2 / 고1 / 학년 미입력)."""

    @classmethod
    def setUpTestData(cls):
        cls.course = Course.objects.create(name="로직엔제")
        cls.week1 = CourseWeek.objects.create(course=cls.course, week_no=1, title="1주차")
        cls.week2 = CourseWeek.objects.create(course=cls.course, week_no=2, title="2주차")

        cls.video = Video.objects.create(
            course_week=cls.week1,
            title="1주차 1강",
            sequence_no=1,
            provider=Video.Provider.MUX,
            external_ref="asset-week1-1",
            duration_seconds=3600,
            status=Video.Status.PUBLISHED,
        )
        cls.video_w2 = Video.objects.create(
            course_week=cls.week2, title="2주차 1강", status=Video.Status.PUBLISHED
        )
        cls.video_preparing = Video.objects.create(
            course_week=cls.week1, title="1주차 2강", status=Video.Status.PREPARING
        )
        cls.video_archived = Video.objects.create(
            course_week=cls.week1, title="1주차 3강", status=Video.Status.ARCHIVED
        )
        cls.video_special = Video.objects.create(
            title="7월 특강", status=Video.Status.PUBLISHED
        )

        cls.s1 = make_student("stu-1", "김하늘", grade="고2")
        cls.s2 = make_student("stu-2", "이준호", grade="고1")
        cls.s_no_grade = make_student("stu-3", "박서준", grade="")

        cls.parent_user = make_user("par-1", User.Role.PARENT, name="김학부")
        Parent.objects.create(user=cls.parent_user, name="김학부", phone="010-0000-0001")
        cls.owner = make_user("owner-1", User.Role.OWNER, name="대표")

    def grant(self, student, video, **kwargs):
        """영상 1개당 권한 1행 — 지급 단위가 주차에서 영상으로 바뀌었다(2026-08-04)."""
        kwargs.setdefault("source", VideoGrant.Source.ATTENDANCE_AUTO)
        kwargs.setdefault("granted_at", NOW)
        kwargs.setdefault("expires_at", NOW + GRANT_DURATION)
        return VideoGrant.objects.create(student=student, video=video, **kwargs)

    def play(self, video, at=NOW):
        with freeze_now(at):
            return self.client.get(playback_url(video))

    def assert_not_found(self, response):
        """차단은 우리 API 의 404 여야 한다 — 라우트 부재(HTML 404)와 구분한다."""
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "찾을 수 없습니다.")


class PlaybackAccessTests(PlaybackFixtureMixin, TestCase):
    """권한 강제 — 권한 없는 학생은 video_id 를 알아도 못 본다."""

    def test_granted_student_can_play(self):
        self.grant(self.s1, self.video)
        self.client.force_login(self.s1.user)
        response = self.play(self.video)
        self.assertEqual(response.status_code, 200)
        video = response.json()["video"]
        self.assertEqual(video["video_id"], self.video.video_id)
        self.assertEqual(video["title"], "1주차 1강")
        self.assertEqual(video["provider"], "mux")
        self.assertEqual(video["external_ref"], "asset-week1-1")
        self.assertEqual(video["duration_seconds"], 3600)
        self.assertEqual(video["course_name"], "로직엔제")
        self.assertEqual(video["week_no"], 1)

    def test_expires_at_comes_from_the_grant(self):
        # 재생 화면이 "언제 사라지는가"를 아는 유일한 근거(PRD 3.1.4 ⑥ 7일 만료)
        self.grant(self.s1, self.video)
        self.client.force_login(self.s1.user)
        response = self.play(self.video)
        self.assertEqual(
            response.json()["expires_at"],
            timezone.localtime(NOW + GRANT_DURATION).isoformat(),
        )

    def test_student_without_grant_is_not_found(self):
        self.client.force_login(self.s1.user)
        self.assert_not_found(self.play(self.video))

    def test_expired_grant_is_not_found(self):
        self.grant(self.s1, self.video, expires_at=NOW - datetime.timedelta(seconds=1))
        self.client.force_login(self.s1.user)
        self.assert_not_found(self.play(self.video))

    def test_expiry_boundary_is_closed(self):
        # active() 계약: expires_at == 기준 시각은 이미 만료다(경계 미포함)
        self.grant(self.s1, self.video, expires_at=NOW)
        self.client.force_login(self.s1.user)
        self.assert_not_found(self.play(self.video))

    def test_revoked_grant_is_not_found(self):
        self.grant(self.s1, self.video, revoked_at=NOW - datetime.timedelta(days=1))
        self.client.force_login(self.s1.user)
        self.assert_not_found(self.play(self.video))

    def test_other_students_grant_does_not_unlock(self):
        self.grant(self.s2, self.video)
        self.client.force_login(self.s1.user)
        self.assert_not_found(self.play(self.video))

    def test_grant_for_another_video_does_not_unlock(self):
        # 지급 단위는 영상 1개 — 2주차 1강 권한으로 1주차 1강을 열 수 없다
        self.grant(self.s1, self.video_w2)
        self.client.force_login(self.s1.user)
        self.assert_not_found(self.play(self.video))

    def test_grant_survives_the_video_moving_to_another_week(self):
        # 지급 단위를 영상으로 바꾼 이유(2026-08-04): 권한은 영상에 붙어 있으므로
        # 관리자가 콘텐츠 분류(주차)를 고쳐도 이미 지급된 권한은 끊기지 않는다
        self.grant(self.s1, self.video)
        self.video.course_week = self.week2
        self.video.save(update_fields=["course_week"])
        self.client.force_login(self.s1.user)
        response = self.play(self.video)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["video"]["week_no"], 2)

    def test_preparing_video_is_not_found(self):
        # 이중 게이트: 그 영상에 권한이 있어도 `공개` 가 아니면 없는 것이다
        self.grant(self.s1, self.video_preparing)
        self.client.force_login(self.s1.user)
        self.assert_not_found(self.play(self.video_preparing))

    def test_archived_video_is_not_found(self):
        self.grant(self.s1, self.video_archived)
        self.client.force_login(self.s1.user)
        self.assert_not_found(self.play(self.video_archived))

    def test_week_less_video_is_not_found(self):
        # 주차 무관 특강은 자동지급(그 주차의 공개 영상) 대상이 아니다 —
        # 권한이 없으니 다른 영상 권한을 들고 있어도 404
        self.grant(self.s1, self.video)
        self.client.force_login(self.s1.user)
        self.assert_not_found(self.play(self.video_special))

    def test_unknown_video_id_is_not_found(self):
        self.grant(self.s1, self.video)
        self.client.force_login(self.s1.user)
        self.assert_not_found(self.play(99999))

    def test_makeup_grant_source_also_plays(self):
        # 권한 원천은 VideoGrant 하나 — 동보 승인이 만든 권한도 같은 경로로 열린다
        self.grant(self.s1, self.video, source=VideoGrant.Source.MAKEUP)
        self.client.force_login(self.s1.user)
        self.assertEqual(self.play(self.video).status_code, 200)

    def test_parent_cannot_play(self):
        self.grant(self.s1, self.video)
        self.client.force_login(self.parent_user)
        self.assertEqual(self.play(self.video).status_code, 403)

    def test_staff_cannot_play_through_student_route(self):
        self.grant(self.s1, self.video)
        self.client.force_login(self.owner)
        self.assertEqual(self.play(self.video).status_code, 403)

    def test_anonymous_cannot_play(self):
        self.grant(self.s1, self.video)
        self.assertEqual(self.play(self.video).status_code, 403)

    def test_student_role_without_student_row_is_not_found(self):
        orphan = make_user("stu-orphan", User.Role.STUDENT, name="유령")
        self.client.force_login(orphan)
        self.assert_not_found(self.play(self.video))


class PlaybackWatermarkTests(PlaybackFixtureMixin, TestCase):
    """워터마크는 서버가 만든다 — 학년 · 이름 · 시청 날짜(Asia/Seoul)."""

    def setUp(self):
        self.grant(self.s1, self.video)
        self.grant(self.s_no_grade, self.video)

    def test_watermark_is_grade_name_and_watched_date(self):
        self.client.force_login(self.s1.user)
        response = self.play(self.video)
        self.assertEqual(response.json()["watermark"], "고2 · 김하늘 · 2026-07-30")

    def test_watched_date_follows_the_server_clock(self):
        self.client.force_login(self.s1.user)
        later = NOW + datetime.timedelta(days=3)
        self.assertEqual(
            self.play(self.video, at=later).json()["watermark"],
            "고2 · 김하늘 · 2026-08-02",
        )

    def test_watched_date_is_asia_seoul_not_utc(self):
        # UTC 07-30 16:00 = KST 07-31 01:00 — 날짜가 UTC 로 새면 07-30 이 찍힌다
        self.client.force_login(self.s1.user)
        utc_evening = datetime.datetime(2026, 7, 30, 16, 0, tzinfo=datetime.UTC)
        self.assertEqual(
            self.play(self.video, at=utc_evening).json()["watermark"],
            "고2 · 김하늘 · 2026-07-31",
        )

    def test_blank_grade_drops_the_piece_without_a_dangling_separator(self):
        # 학년은 관리자 입력 메타 — 비어 있다고 재생을 막지 않는다(학생 잘못이 아니다)
        self.client.force_login(self.s_no_grade.user)
        response = self.play(self.video)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["watermark"], "박서준 · 2026-07-30")

    def test_watermark_pieces_are_not_shipped_separately(self):
        # 클라이언트 조립 금지 — 조각을 내리면 프런트가 다시 조립할 수 있게 된다
        self.client.force_login(self.s1.user)
        body = self.play(self.video).json()
        self.assertIsInstance(body["watermark"], str)
        self.assertNotIn("student", body)

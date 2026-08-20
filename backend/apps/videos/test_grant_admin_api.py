"""영상 권한 개별 회수·회수 취소 — 지급 내역 (FLOW §5).

**손으로 하는 것은 회수와 그 취소뿐이다.** 지급은 `출결 확정` 이 묶음으로 하고
(3-5) 수동 지급은 만들지 않기로 했다(§5) — 대신 **회수를 무를 수 있어야 한다.**
이름이 줄지어 선 화면에서 옆줄을 누르면 되돌릴 길이 없기 때문이다.

회수는 `revoked_at` 스탬프다 — 행을 지우지 않는다. 소비자 진입이
`VideoGrant.objects.active()` 하나라(모델 계약) 스탬프만으로 시청이 끊긴다.
취소는 그 스탬프만 지운다 — **만료는 처음 준 시점 그대로**라, 잘못 누른 회수
한 번이 시청 기간을 늘리지 않는다.
"""
import datetime

from django.test import TestCase
from django.utils import timezone

from apps.accounts.features import FeatureKey
from apps.accounts.models import StaffFeatureGrant, Student, User

from .models import Video, VideoGrant

PASSWORD = "pw-Secret-77!"


class GrantAdminApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            login_id="vg-adm", password=PASSWORD, name="관리자", role=User.Role.ADMIN
        )
        cls.assistant = User.objects.create_user(
            login_id="vg-ast", password=PASSWORD, name="조교", role=User.Role.ASSISTANT
        )
        cls.student = Student.objects.create(
            user=User.objects.create_user(
                login_id="vg-stu", password=PASSWORD, name="김하늘", role=User.Role.STUDENT
            ),
            matching_key="김하늘1234",
        )
        cls.video = Video.objects.create(title="3주차 1강", status=Video.Status.PUBLISHED)
        now = timezone.now()
        cls.grant = VideoGrant.objects.create(
            student=cls.student,
            video=cls.video,
            source=VideoGrant.Source.ATTENDANCE_AUTO,
            granted_at=now,
            expires_at=now + datetime.timedelta(days=7),
        )

    def setUp(self):
        self.client.force_login(self.admin)

    def revoke_url(self, grant):
        return f"/api/admin/videos/grants/{grant.grant_id}/revoke"

    def unrevoke_url(self, grant):
        return f"/api/admin/videos/grants/{grant.grant_id}/unrevoke"

    def test_grants_are_listed_with_the_student_and_video(self):
        rows = self.client.get("/api/admin/videos/grants").json()["grants"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["student"]["name"], "김하늘")
        self.assertEqual(rows[0]["video_title"], "3주차 1강")
        self.assertIsNone(rows[0]["revoked_at"])

    def test_the_list_filters_by_student_and_video(self):
        other = Student.objects.create(matching_key="이서준5678")
        VideoGrant.objects.create(
            student=other,
            video=self.video,
            source=VideoGrant.Source.MAKEUP,
            granted_at=timezone.now(),
            expires_at=timezone.now() + datetime.timedelta(days=7),
        )
        url = f"/api/admin/videos/grants?student_id={self.student.student_id}"
        self.assertEqual(len(self.client.get(url).json()["grants"]), 1)
        url = f"/api/admin/videos/grants?video_id={self.video.video_id}"
        self.assertEqual(len(self.client.get(url).json()["grants"]), 2)

    def test_a_bad_filter_is_a_400_not_an_empty_list(self):
        # 빈 목록으로 돌아오면 "권한이 하나도 없다" 로 읽힌다(payment_admin 선례).
        self.assertEqual(
            self.client.get("/api/admin/videos/grants?student_id=abc").status_code, 400
        )

    def test_revoking_kills_playback_but_keeps_the_row(self):
        response = self.client.post(self.revoke_url(self.grant))
        self.assertEqual(response.status_code, 200)
        self.grant.refresh_from_db()
        self.assertIsNotNone(self.grant.revoked_at)
        self.assertEqual(VideoGrant.objects.count(), 1)
        self.assertEqual(VideoGrant.objects.active().count(), 0)

    def test_revoking_twice_keeps_the_first_time(self):
        self.client.post(self.revoke_url(self.grant))
        self.grant.refresh_from_db()
        first = self.grant.revoked_at
        self.client.post(self.revoke_url(self.grant))
        self.grant.refresh_from_db()
        self.assertEqual(self.grant.revoked_at, first)

    def test_revoking_needs_the_video_feature(self):
        # 조교 프리셋에 `영상지급관리` 가 없다 — 기본 차단이다.
        self.client.force_login(self.assistant)
        self.assertEqual(self.client.post(self.revoke_url(self.grant)).status_code, 403)
        StaffFeatureGrant.objects.create(
            user=self.assistant,
            feature_key=FeatureKey.VIDEO_GRANT_ADMIN,
            is_granted=True,
        )
        self.assertEqual(self.client.post(self.revoke_url(self.grant)).status_code, 200)

    def test_unknown_grant_is_404(self):
        self.assertEqual(
            self.client.post("/api/admin/videos/grants/999999/revoke").status_code, 404
        )

    def test_unrevoking_puts_the_video_back(self):
        self.client.post(self.revoke_url(self.grant))
        response = self.client.post(self.unrevoke_url(self.grant))
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["grant"]["revoked_at"])
        self.grant.refresh_from_db()
        self.assertIsNone(self.grant.revoked_at)
        self.assertEqual(VideoGrant.objects.active().count(), 1)

    def test_unrevoking_keeps_the_original_expiry(self):
        """무르는 것은 회수이지 지급이 아니다 — 만료를 다시 잡으면 수동 지급의 뒷문이다."""
        granted_at, expires_at = self.grant.granted_at, self.grant.expires_at
        self.client.post(self.revoke_url(self.grant))
        self.client.post(self.unrevoke_url(self.grant))
        self.grant.refresh_from_db()
        self.assertEqual(self.grant.granted_at, granted_at)
        self.assertEqual(self.grant.expires_at, expires_at)

    def test_unrevoking_an_expired_grant_does_not_revive_it(self):
        expired = VideoGrant.objects.create(
            student=self.student,
            video=Video.objects.create(title="2주차 1강", status=Video.Status.PUBLISHED),
            source=VideoGrant.Source.MAKEUP,
            granted_at=timezone.now() - datetime.timedelta(days=14),
            expires_at=timezone.now() - datetime.timedelta(days=7),
            revoked_at=timezone.now(),
        )
        self.client.post(self.unrevoke_url(expired))
        expired.refresh_from_db()
        self.assertIsNone(expired.revoked_at)
        self.assertNotIn(expired, VideoGrant.objects.active())

    def test_unrevoking_a_live_grant_changes_nothing(self):
        self.assertEqual(self.client.post(self.unrevoke_url(self.grant)).status_code, 200)
        self.grant.refresh_from_db()
        self.assertIsNone(self.grant.revoked_at)

    def test_unrevoking_needs_the_video_feature(self):
        self.client.force_login(self.assistant)
        self.assertEqual(self.client.post(self.unrevoke_url(self.grant)).status_code, 403)

    def test_unknown_grant_is_404_on_unrevoke(self):
        self.assertEqual(
            self.client.post("/api/admin/videos/grants/999999/unrevoke").status_code, 404
        )

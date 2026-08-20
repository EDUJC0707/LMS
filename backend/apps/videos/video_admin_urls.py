"""복습영상 등록·관리 라우팅 (/api/admin/videos*).

역할 경로라 도메인 리소스 라우터(`urls.py`)와 분리한다 — playback_urls·
makeup_urls 선례. config.urls 가 접두 없이 include 한다.
"""
from django.urls import path

from . import views

app_name = "video_admin"

urlpatterns = [
    path("admin/videos", views.AdminVideoListView.as_view(), name="admin-video-list"),
    # 고정 경로를 <int:video_id> 보다 먼저 — int 컨버터라 충돌하지 않지만
    # 순서로 못박아 둔다(경로가 늘어날 때 사고를 막는다).
    path(
        "admin/videos/course-weeks",
        views.AdminVideoCourseWeekListView.as_view(),
        name="admin-video-course-weeks",
    ),
    path(
        "admin/videos/grants",
        views.AdminVideoGrantListView.as_view(),
        name="admin-video-grants",
    ),
    path(
        "admin/videos/grants/<int:grant_id>/revoke",
        views.AdminVideoGrantRevokeView.as_view(),
        name="admin-video-grant-revoke",
    ),
    path(
        "admin/videos/grants/<int:grant_id>/unrevoke",
        views.AdminVideoGrantUnrevokeView.as_view(),
        name="admin-video-grant-unrevoke",
    ),
    path(
        "admin/videos/uploads",
        views.AdminVideoUploadView.as_view(),
        name="admin-video-upload",
    ),
    path(
        "admin/videos/<int:video_id>",
        views.AdminVideoDetailView.as_view(),
        name="admin-video-detail",
    ),
    path(
        "admin/videos/<int:video_id>/publish",
        views.AdminVideoPublishView.as_view(),
        name="admin-video-publish",
    ),
    path(
        "admin/videos/<int:video_id>/preview",
        views.AdminVideoPreviewView.as_view(),
        name="admin-video-preview",
    ),
    path(
        "admin/videos/<int:video_id>/sync",
        views.AdminVideoSyncView.as_view(),
        name="admin-video-sync",
    ),
    path(
        "admin/videos/<int:video_id>/archive",
        views.AdminVideoArchiveView.as_view(),
        name="admin-video-archive",
    ),
]

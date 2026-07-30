"""복습영상 재생 라우트 — /api/ 바로 아래 마운트된다(config.urls).

역할 경로(/student/*)라 도메인 리소스 라우터(urls.py)와 분리한다
(makeup_urls·curriculum home_urls 선례).
"""
from django.urls import path

from . import views

app_name = "video_playback"

urlpatterns = [
    path(
        "student/videos/<int:video_id>/playback",
        views.StudentVideoPlaybackView.as_view(),
        name="student-video-playback",
    ),
]

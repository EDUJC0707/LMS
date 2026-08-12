"""결석 상담 라우트(8차) — /api/ 바로 아래 마운트된다(config.urls).

관리자 상담 화면은 역할 경로(/admin/* — PRD §4 URL 구조)를 따르므로
게시판 도메인 라우터(urls.py)와 분리해 둔다(grades admin_urls 선례).
"""
from django.urls import path

from . import views

app_name = "counseling"

urlpatterns = [
    path(
        "admin/counseling/queue",
        views.CounselingQueueView.as_view(),
        name="counseling-queue",
    ),
    path(
        "admin/counseling",
        views.CounselingOpenView.as_view(),
        name="counseling-open",
    ),
    path(
        "admin/counseling/<int:counsel_id>/notify",
        views.CounselingNotifyView.as_view(),
        name="counseling-notify",
    ),
    path(
        "admin/counseling/<int:counsel_id>",
        views.CounselingRecordView.as_view(),
        name="counseling-record",
    ),
]

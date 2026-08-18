"""동보 신청 라우트 — /api/ 바로 아래 마운트된다(config.urls).

소비자 신청은 역할 경로(/student/* /parent/* — PRD §4 URL 구조), 관리자
목록·거절은 /admin/* 을 따르므로 도메인 리소스 라우터(urls.py)와 분리해
둔다(curriculum home_urls·grades admin_urls 선례).
"""
from django.urls import path

from . import views

app_name = "makeup"

urlpatterns = [
    path(
        "student/makeup-request",
        views.StudentMakeupRequestView.as_view(),
        name="student-makeup-request",
    ),
    path(
        "parent/makeup-request",
        views.ParentMakeupRequestView.as_view(),
        name="parent-makeup-request",
    ),
    path(
        "admin/makeup-requests",
        views.AdminMakeupRequestListView.as_view(),
        name="admin-makeup-list",
    ),
    path(
        "admin/makeup-requests/<int:makeup_id>/reject",
        views.AdminMakeupRejectView.as_view(),
        name="admin-makeup-reject",
    ),
]

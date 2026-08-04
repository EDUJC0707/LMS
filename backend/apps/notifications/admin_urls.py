"""알림 관리자 라우트 — /api/ 바로 아래 마운트된다(config.urls).

발송내역 조회는 역할 경로(/admin/* — PRD §4 URL 구조)를 따르므로 소비자
라우트(me_urls.py)·도메인 라우터(urls.py)와 분리한다(clinic·grades 선례).
"""
from django.urls import path

from . import views

app_name = "notifications_admin"

urlpatterns = [
    path(
        "admin/notifications",
        views.AdminNotificationsView.as_view(),
        name="admin-notifications",
    ),
]

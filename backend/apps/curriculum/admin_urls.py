"""관리자 반 개설 라우트 — /api/ 바로 아래 마운트된다(config.urls).

반 목록·개설은 역할 경로(/admin/* — PRD §4 URL 구조)를 따르므로 도메인 리소스
라우터(urls.py)와 분리해 둔다(grades admin_urls 선례).
"""
from django.urls import path

from . import views

app_name = "curriculum_admin"

urlpatterns = [
    path("admin/classes", views.AdminClassListView.as_view(), name="class-list"),
]

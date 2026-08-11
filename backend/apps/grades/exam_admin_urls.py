"""관리자 시험 조회 라우트 — /api/ 바로 아래 마운트된다(config.urls).

관리자 성적처리 화면은 역할 경로(/admin/* — PRD §4 URL 구조)를 따르므로
도메인 리소스 라우터(urls.py)와 분리해 둔다(admin_urls 출결 선례).
"""
from django.urls import path

from . import views

app_name = "exam_admin"

urlpatterns = [
    path("admin/exams", views.AdminExamListView.as_view(), name="exam-list"),
    path("admin/exams/<int:exam_id>", views.AdminExamDetailView.as_view(), name="exam-detail"),
    path(
        "admin/exams/<int:exam_id>/questions",
        views.AdminExamQuestionsView.as_view(),
        name="exam-questions",
    ),
]

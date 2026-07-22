"""성적·성적표 조회 라우트 — /api/ 바로 아래 마운트된다(config.urls).

소비자 성적표는 도메인 prefix(/api/grades/)가 아니라 역할 경로
(/student/* /parent/* — PRD §4 URL 구조·key_considerations §3)를 따르므로
도메인 리소스 라우터(urls.py)와 분리해 둔다(curriculum home_urls 선례).
"""
from django.urls import path

from . import views

app_name = "grade_report"

urlpatterns = [
    path("student/grades", views.StudentGradeListView.as_view(), name="student-grade-list"),
    path(
        "student/grades/<int:exam_id>",
        views.StudentGradeReportView.as_view(),
        name="student-grade-report",
    ),
    path("parent/grades", views.ParentGradeListView.as_view(), name="parent-grade-list"),
    path(
        "parent/grades/<int:exam_id>",
        views.ParentGradeReportView.as_view(),
        name="parent-grade-report",
    ),
]

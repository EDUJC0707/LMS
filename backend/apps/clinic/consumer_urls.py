"""클리닉 소비자 라우트 — /api/ 바로 아래 마운트된다(config.urls).

학생 클리닉 신청은 역할 경로(/student/* — PRD §4 URL 구조)를 따르므로
도메인 리소스 라우터(urls.py)와 분리해 둔다(curriculum home_urls 선례).
"""
from django.urls import path

from . import views

app_name = "clinic_consumer"

urlpatterns = [
    path("student/clinic", views.StudentClinicView.as_view(), name="student-clinic"),
    path(
        "student/clinic/requests",
        views.ClinicRequestCreateView.as_view(),
        name="student-clinic-request-create",
    ),
    path(
        "student/clinic/requests/<int:clinic_id>",
        views.ClinicRequestChangeView.as_view(),
        name="student-clinic-request-change",
    ),
    path(
        "student/clinic/requests/<int:clinic_id>/cancel",
        views.ClinicRequestCancelView.as_view(),
        name="student-clinic-request-cancel",
    ),
]

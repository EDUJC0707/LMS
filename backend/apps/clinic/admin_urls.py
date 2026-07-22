"""클리닉 관리자 라우트(8차) — /api/ 바로 아래 마운트된다(config.urls).

관리자 배정·출결·평가는 역할 경로(/admin/* — PRD §4 URL 구조)를 따르므로
소비자 라우트(consumer_urls.py)·도메인 라우터(urls.py)와 분리해 둔다
(grades admin_urls 선례).
"""
from django.urls import path

from . import views

app_name = "clinic_admin"

urlpatterns = [
    path(
        "admin/clinic/requests",
        views.AdminClinicQueueView.as_view(),
        name="clinic-queue",
    ),
    path(
        "admin/clinic/requests/<int:clinic_id>/assign",
        views.AdminClinicAssignView.as_view(),
        name="clinic-assign",
    ),
    path(
        "admin/clinic/requests/<int:clinic_id>/reject",
        views.AdminClinicRejectView.as_view(),
        name="clinic-reject",
    ),
    path(
        "admin/clinic/requests/<int:clinic_id>/attendance",
        views.AdminClinicAttendanceView.as_view(),
        name="clinic-attendance",
    ),
    path(
        "admin/clinic/requests/<int:clinic_id>/evaluation",
        views.AdminClinicEvaluationView.as_view(),
        name="clinic-evaluation",
    ),
    path(
        "admin/clinic/eval-criteria",
        views.AdminClinicCriteriaView.as_view(),
        name="clinic-eval-criteria",
    ),
    path(
        "admin/clinic/students/<int:student_id>/unban",
        views.AdminClinicUnbanView.as_view(),
        name="clinic-unban",
    ),
]

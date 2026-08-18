"""관리자 운영 라우트(8차) — /api/ 바로 아래 마운트된다(config.urls).

직원 권한 매트릭스·직원 계정·계정 일괄 발급·학생 명부는 역할 경로
(/admin/* — PRD §4 URL 구조)를 따르므로 도메인 리소스 라우터(urls.py)와
분리해 둔다(grades admin_urls 선례).

`admin/students` 는 `admin/staff/...` 보다 뒤에 오지만 세그먼트가 겹치지
않아 순서 의존이 없다.
"""
from django.urls import path

from . import views

app_name = "accounts_admin"

urlpatterns = [
    path("admin/staff", views.StaffMatrixView.as_view(), name="staff-matrix"),
    path(
        "admin/staff/<int:user_id>/features",
        views.StaffFeaturesView.as_view(),
        name="staff-features",
    ),
    path(
        "admin/staff/<int:user_id>/deactivate",
        views.StaffDeactivateView.as_view(),
        name="staff-deactivate",
    ),
    path(
        "admin/staff/<int:user_id>/activate",
        views.StaffActivateView.as_view(),
        name="staff-activate",
    ),
    path("admin/students", views.StudentDirectoryView.as_view(), name="student-directory"),
    path("admin/accounts/bulk", views.AccountBulkIssueView.as_view(), name="accounts-bulk"),
    path(
        "admin/accounts/<int:student_id>/register",
        views.AccountRegisterView.as_view(),
        name="accounts-register",
    ),
    path(
        "admin/accounts/<int:user_id>/password",
        views.AccountPasswordResetView.as_view(),
        name="accounts-password",
    ),
]

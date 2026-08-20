"""관리자 출결 라우트 — /api/ 바로 아래 마운트된다(config.urls).

관리자 출결 화면은 도메인 prefix(/api/grades/)가 아니라 역할 경로
(/admin/* — PRD §4 URL 구조·key_considerations §3)를 따르므로 도메인 리소스
라우터(urls.py)와 분리해 둔다(curriculum home_urls 선례).
"""
from django.urls import path

from . import views

app_name = "attendance_admin"

urlpatterns = [
    path(
        "admin/attendance/sessions",
        views.AttendanceSessionListView.as_view(),
        name="attendance-session-list",
    ),
    path(
        "admin/attendance/sessions/<int:session_id>",
        views.AttendanceSessionDetailView.as_view(),
        name="attendance-session-detail",
    ),
    path(
        "admin/attendance/sessions/<int:session_id>/notify",
        views.AttendanceNoticeView.as_view(),
        name="attendance-session-notify",
    ),
    path(
        "admin/attendance/sessions/<int:session_id>/reports",
        views.AttendanceSessionReportsView.as_view(),
        name="attendance-session-reports",
    ),
    path(
        "admin/attendance/sessions/<int:session_id>/onsite",
        views.AttendanceOnsiteView.as_view(),
        name="attendance-session-onsite",
    ),
    path(
        "admin/attendance/makeup",
        views.MakeupCheckView.as_view(),
        name="attendance-makeup",
    ),
    path(
        "admin/attendance/withdraw",
        views.AttendanceWithdrawView.as_view(),
        name="attendance-withdraw",
    ),
]

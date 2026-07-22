"""워크북 사진 라우트 — /api/ 바로 아래 마운트된다(config.urls).

역할 경로(/admin/* · /student/* · /parent/* — PRD §4 URL 구조·key_considerations
§3)를 따르므로 도메인 리소스 라우터(urls.py)와 분리해 둔다(makeup_urls 선례 —
관리자·소비자 라우트를 슬라이스 단위 한 파일에 모은다).
"""
from django.urls import path

from . import views

app_name = "workbook"

urlpatterns = [
    path(
        "admin/workbook/upload",
        views.AdminWorkbookUploadView.as_view(),
        name="admin-workbook-upload",
    ),
    path(
        "admin/workbook",
        views.AdminWorkbookListView.as_view(),
        name="admin-workbook-list",
    ),
    path(
        "admin/workbook/<int:submission_id>/match",
        views.AdminWorkbookMatchView.as_view(),
        name="admin-workbook-match",
    ),
    path(
        "admin/workbook/<int:submission_id>",
        views.AdminWorkbookDetailView.as_view(),
        name="admin-workbook-detail",
    ),
    path(
        "student/workbook",
        views.StudentWorkbookView.as_view(),
        name="student-workbook",
    ),
    path(
        "parent/workbook",
        views.ParentWorkbookView.as_view(),
        name="parent-workbook",
    ),
]

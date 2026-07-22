"""캘린더 홈 라우트 — /api/ 바로 아래 마운트된다(config.urls, auth_urls 선례).

소비자 홈은 도메인 prefix(/api/curriculum/)가 아니라 역할 경로
(/student/* /parent/* — PRD §4 URL 구조·key_considerations §3)를 따르므로
도메인 리소스 라우터(urls.py)와 분리해 둔다.
"""
from django.urls import path

from . import views

app_name = "home"

urlpatterns = [
    path("student/home", views.StudentHomeView.as_view(), name="student-home"),
    path("parent/home", views.ParentHomeView.as_view(), name="parent-home"),
]

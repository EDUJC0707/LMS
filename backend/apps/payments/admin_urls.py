"""교재 결제 관리자 라우트 — /api/ 바로 아래 마운트된다(config.urls).

결제·배부 상태 조회는 역할 경로(/admin/* — PRD §4 URL 구조)를 따르므로
소비자 라우트(consumer_urls.py)·도메인 라우터(urls.py)와 분리한다
(notifications·clinic·grades 선례).
"""
from django.urls import path

from . import views

app_name = "payments_admin"

urlpatterns = [
    path("admin/payments", views.AdminPaymentListView.as_view(), name="admin-payments"),
]

"""교재 결제 소비자 라우트 — /api/ 바로 아래 마운트된다(config.urls).

학생·학부모 결제 조회는 역할 경로(/student/*·/parent/* — PRD §4 URL 구조)를
따르므로 도메인 리소스 라우터(urls.py)와 분리해 둔다(clinic consumer_urls·
curriculum home_urls 선례).
"""
from django.urls import path

from . import views

app_name = "payments_consumer"

urlpatterns = [
    path("student/payments", views.StudentPaymentListView.as_view(), name="student-payments"),
    path("student/payments/bill", views.StudentBillView.as_view(), name="student-bill"),
    path("parent/payments", views.ParentPaymentListView.as_view(), name="parent-payments"),
    path("parent/payments/bill", views.ParentBillView.as_view(), name="parent-bill"),
]

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
    path("admin/payments/bill", views.AdminBillView.as_view(), name="admin-bill"),
    # 잔액은 목록보다 앞에 둔다 — <int:order_id> 보다 먼저 매칭돼야 한다.
    path(
        "admin/payments/balance",
        views.AdminPaymentBalanceView.as_view(),
        name="admin-payment-balance",
    ),
    # 반 단위 교재는 <int:order_id> 보다 앞에 둔다(int 컨버터라 겹치진 않는다).
    path(
        "admin/payments/classes",
        views.AdminGoodsClassListView.as_view(),
        name="admin-goods-classes",
    ),
    path(
        "admin/payments/classes/<int:class_id>",
        views.AdminGoodsClassView.as_view(),
        name="admin-goods-class",
    ),
    path(
        "admin/payments/classes/<int:class_id>/deliver",
        views.AdminGoodsDeliverView.as_view(),
        name="admin-goods-deliver",
    ),
    path(
        "admin/payments/classes/<int:class_id>/undeliver",
        views.AdminGoodsUndeliverView.as_view(),
        name="admin-goods-undeliver",
    ),
    path(
        "admin/payments/<int:order_id>/cancel",
        views.AdminPaymentCancelView.as_view(),
        name="admin-payment-cancel",
    ),
    path(
        "admin/payments/<int:order_id>/deliver",
        views.AdminPaymentDeliverView.as_view(),
        name="admin-payment-deliver",
    ),
    path(
        "admin/payments/<int:order_id>/undeliver",
        views.AdminPaymentUndeliverView.as_view(),
        name="admin-payment-undeliver",
    ),
]

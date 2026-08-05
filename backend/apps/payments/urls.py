"""payments API 라우팅. config.urls 의 /api/payments/ 에 마운트된다.

업체 결제 승인 콜백이 여기 붙는다 — **역할 경로가 아니다**. 부르는 쪽이
학생도 학부모도 직원도 아닌 업체 서버라서 `/student/*`·`/admin/*` 어디에도
속하지 않는다(소비자·관리자 라우트는 consumer_urls·admin_urls 로 분리).
"""
from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

app_name = "payments"

router = DefaultRouter()

urlpatterns = [
    path("callback", views.PaymentCallbackView.as_view(), name="callback"),
    *router.urls,
]

"""내 알림 내역 라우트(8차) — /api/ 바로 아래 마운트된다(config.urls).

/api/me 계열(상태 기반 노출 관문 — accounts.auth_urls)과 같은 축이지만
소유 도메인이 notifications 라 여기서 마운트한다(도메인 소유 원칙).
"""
from django.urls import path

from . import views

app_name = "notifications_me"

urlpatterns = [
    path("me/notifications", views.MeNotificationsView.as_view(), name="me-notifications"),
]

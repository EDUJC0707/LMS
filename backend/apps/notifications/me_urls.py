"""내 알림 내역 라우트(8차) — /api/ 바로 아래 마운트된다(config.urls).

/api/me 계열(상태 기반 노출 관문 — accounts.auth_urls)과 같은 축이지만
소유 도메인이 notifications 라 여기서 마운트한다(도메인 소유 원칙).
"""
from django.urls import path

from . import views

app_name = "notifications_me"

urlpatterns = [
    path("me/notifications", views.MeNotificationsView.as_view(), name="me-notifications"),
    # `read-all` 이 `<int:notif_id>` 보다 위에 있을 필요는 없다 — 정수가 아니라
    # 두 패턴이 겹치지 않는다. 읽기 좋은 순서로 둔다.
    path(
        "me/notifications/read-all",
        views.MeNotificationReadView.as_view(),
        name="me-notifications-read-all",
    ),
    path(
        "me/notifications/<int:notif_id>/read",
        views.MeNotificationReadView.as_view(),
        name="me-notification-read",
    ),
]

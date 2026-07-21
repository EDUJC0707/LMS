"""루트 URL 설정.

- /healthz         헬스체크(로드밸런서/배포 점검용 경량 엔드포인트)
- /admin/          Django 관리자
- /api/<도메인>/   도메인별 DRF 라우터(각 앱 urls.py 에서 마운트)
- /api-auth/       DRF 브라우저블 API 로그인
"""
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path


def healthz(_request):
    return JsonResponse({"status": "ok"})


# /api/ 하위 도메인 라우터. 각 앱의 urls.py 는 DefaultRouter placeholder.
api_urlpatterns = [
    path("accounts/", include("apps.accounts.urls")),
    path("grades/", include("apps.grades.urls")),
    path("curriculum/", include("apps.curriculum.urls")),
    path("videos/", include("apps.videos.urls")),
    path("payments/", include("apps.payments.urls")),
    path("clinic/", include("apps.clinic.urls")),
    path("boards/", include("apps.boards.urls")),
    path("notifications/", include("apps.notifications.urls")),
]

urlpatterns = [
    path("healthz", healthz),
    path("admin/", admin.site.urls),
    path("api/", include(api_urlpatterns)),
    path("api-auth/", include("rest_framework.urls")),
]

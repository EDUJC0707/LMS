"""루트 URL 설정.

- /healthz         헬스체크(로드밸런서/배포 점검용 경량 엔드포인트)
- /sentry-debug    Sentry 수집 확인용(토큰 필요, 없으면 404)
- /admin/          Django 관리자
- /api/<도메인>/   도메인별 DRF 라우터(각 앱 urls.py 에서 마운트)
- /api-auth/       DRF 브라우저블 API 로그인
"""
import secrets

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import Http404, JsonResponse
from django.urls import include, path


def healthz(_request):
    return JsonResponse({"status": "ok"})


def sentry_debug(request):
    """일부러 500 을 낸다 — Sentry 가 실제 웹 요청 경로에서 수집하는지 확인용.

    `SENTRY_DEBUG_TOKEN` 이 비어 있거나 토큰이 틀리면 404 다. 상시 열린 500
    엔드포인트를 두지 않으려는 것 — 기본값은 닫힘이고, 확인이 끝나면 시크릿을
    지워 다시 닫는다(infra/DEPLOY.md 8장).
    """
    token = settings.SENTRY_DEBUG_TOKEN
    # compare_digest 는 str 끼리는 ASCII 만 받는다 — 한글 토큰이 오면 터진다. bytes 로 비교.
    if not token or not secrets.compare_digest(
        request.GET.get("token", "").encode(), token.encode()
    ):
        raise Http404

    raise RuntimeError("Sentry 수집 확인용 예외")


# /api/ 하위 도메인 라우터. 각 앱의 urls.py 는 DefaultRouter placeholder.
api_urlpatterns = [
    # 인증(/api/auth/*)·/api/me — 도메인 prefix 없이 직결(PRD §4 로그인 3종)
    path("", include("apps.accounts.auth_urls")),
    # 캘린더 홈(/api/student/home·/api/parent/home) — 역할 경로 직결(PRD 3.2.0)
    path("", include("apps.curriculum.home_urls")),
    # 관리자 출결(/api/admin/attendance/*) — 역할 경로 직결(PRD 3.1.6)
    path("", include("apps.grades.admin_urls")),
    # 성적·성적표 조회(/api/student/grades* · /api/parent/grades*) — PRD 3.2.1
    path("", include("apps.grades.report_urls")),
    # 관리자 성적처리 조회(/api/admin/exams*) — 역할 경로 직결(PRD 3.1.1)
    path("", include("apps.grades.exam_admin_urls")),
    # 워크북 사진(/api/admin/workbook* · /api/student·parent/workbook) — PRD 3.1.7
    path("", include("apps.grades.workbook_urls")),
    # 동보 신청(/api/student·parent/makeup-request, /api/admin/makeup-requests)
    path("", include("apps.videos.makeup_urls")),
    # 복습영상 재생(/api/student/videos/{id}/playback) — 역할 경로 직결(PRD 3.1.3)
    path("", include("apps.videos.playback_urls")),
    # 복습영상 등록·관리(/api/admin/videos*) — 역할 경로 직결(PRD 3.1.3)
    path("", include("apps.videos.video_admin_urls")),
    # 클리닉 신청(/api/student/clinic*) — 역할 경로 직결(PRD 3.2.4)
    path("", include("apps.clinic.consumer_urls")),
    # 교재 결제 조회(/api/student/payments · /api/parent/payments) — PRD 3.2.5
    path("", include("apps.payments.consumer_urls")),
    # 관리자 결제·배부 상태(/api/admin/payments) — PRD 3.1.5
    path("", include("apps.payments.admin_urls")),
    # 관리자 운영(/api/admin/staff*·/api/admin/accounts*) — 8차(PRD §4·3.1.5)
    path("", include("apps.accounts.admin_urls")),
    # 클리닉 관리자(/api/admin/clinic/*) — 8차(PRD 3.2.4)
    path("", include("apps.clinic.admin_urls")),
    # 결석 상담(/api/admin/counseling/*) — 8차(PRD 3.1.9·8-18)
    path("", include("apps.boards.counseling_urls")),
    # 내 알림 내역(/api/me/notifications) — 8차(설계 도메인 8)
    path("", include("apps.notifications.me_urls")),
    # 관리자 발송내역(/api/admin/notifications) — PRD 3.1.2
    path("", include("apps.notifications.admin_urls")),
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
    path("sentry-debug", sentry_debug),
    path("admin/", admin.site.urls),
    path("api/", include(api_urlpatterns)),
    path("api-auth/", include("rest_framework.urls")),
]

# 개발 편의: DEBUG 에서만 로컬 미디어(워크북 사진 등) 서빙 — 운영은 S3(Tigris) url().
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

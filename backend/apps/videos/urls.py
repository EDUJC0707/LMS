"""videos API 라우팅. config.urls 의 /api/videos/ 에 마운트된다."""
from rest_framework.routers import DefaultRouter

app_name = "videos"

router = DefaultRouter()
# 모델·ViewSet 확정 후 등록: router.register(r"requests", VideoRequestViewSet)

urlpatterns = router.urls

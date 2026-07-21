"""boards API 라우팅. config.urls 의 /api/boards/ 에 마운트된다."""
from rest_framework.routers import DefaultRouter

app_name = "boards"

router = DefaultRouter()
# 모델·ViewSet 확정 후 등록: router.register(r"posts", PostViewSet)

urlpatterns = router.urls

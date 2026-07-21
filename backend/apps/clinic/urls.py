"""clinic API 라우팅. config.urls 의 /api/clinic/ 에 마운트된다."""
from rest_framework.routers import DefaultRouter

app_name = "clinic"

router = DefaultRouter()
# 모델·ViewSet 확정 후 등록: router.register(r"slots", ClinicSlotViewSet)

urlpatterns = router.urls

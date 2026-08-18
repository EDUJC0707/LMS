"""payments 관리자 등록 — 교재(Product).

**오픈 전에 교재를 넣을 방법이 shell 뿐이었다** — `Product` 를 만드는 코드가
시드 하나였고 쓰기 라우트도 화면도 없었다. 교재가 네 행이라 전용 화면을 만들
값이 없어 admin 으로 연다.

주문·결제는 여기 열지 않는다 — 청구·취소는 업체 호출이 딸린 일이라
`/api/admin/payments/*` 로만 다뤄야 하고, admin 에서 행을 직접 고치면 우리
장부만 바뀌고 결제선생은 그대로 남는다.
"""
from django.contrib import admin

from .models import Product


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("product_id", "course", "name", "kind", "price", "is_active")
    list_filter = ("is_active", "kind", "course")
    search_fields = ("name", "course__name")

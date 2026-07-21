"""payments 도메인 — 교재결제·수강료 (DB 설계 도메인 5).

정렬 테이블:
  - products         교재/상품
  - orders           주문(학생·학부모 양측 결제, 청구 sync·중복청구 방지 부분 UQ)
  - payments         결제 provider 추상화
  - tuition_charges  동보생 수강료 청구(makeup_grants 1:1)

placeholder — DB 설계 확정 후 모델 정의.
"""
from django.db import models  # noqa: F401

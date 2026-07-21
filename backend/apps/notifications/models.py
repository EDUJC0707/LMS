"""notifications 도메인 — 알림 (DB 설계 도메인 8).

정렬 테이블:
  - notifications  대상 3분기(student/parent/user), channel/type/status 값집합.
                   동보·수강료·결석상담·상담신청·클리닉리마인더 등 type 값 확장(무마이그레이션).

placeholder — DB 설계 확정 후 모델 정의.
"""
from django.db import models  # noqa: F401

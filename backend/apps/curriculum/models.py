"""curriculum 도메인 — 강좌·주차·캘린더 (DB 설계 도메인 3, 신규 도메인).

정렬 테이블:
  - courses             강좌 마스터
  - course_weeks        주차 + 오프라인 특이사항(주차공지 → 캘린더)
  - week_day_plans      Day 학습계획(주 호버 시 노출)
  - course_enrollments  학생↔강좌/반(캘린더 커리큘럼 렌더 근거)

placeholder — DB 설계 확정 후 모델 정의.
"""
from django.db import models  # noqa: F401

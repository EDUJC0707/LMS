"""clinic 도메인 — 클리닉(오답/약점 보충) (DB 설계 도메인 6).

정렬 테이블:
  - clinic_slots           요일×시간 슬롯·정원
  - clinic_requests        클리닉 신청(슬롯·대상시험·취소, 노쇼 집계)
  - clinic_eligibilities   대상자 판정(출석 + 응시 + 평균미달)
  - clinic_eval_criteria · clinic_evaluations · clinic_evaluation_items
                           평가 기준·결과(녹음경로·AI요약 포함)

placeholder — DB 설계 확정 후 모델 정의.
"""
from django.db import models  # noqa: F401

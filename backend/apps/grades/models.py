"""grades 도메인 — 성적·OMR·과제·약점체크 (DB 설계 도메인 2).

정렬 테이블:
  - class_sessions        수업 회차(↔ course_weeks 매핑)
  - attendances           출결 SSOT — 영상/클리닉/캘린더/리포트 공통 트리거
  - exams · scores        시험 · 성적
  - assignments           과제
  - answer_sheets · sheet_answers   OMR 스캔·문항 채점(추가마킹 포함)
  - questions             시험 문항(테마·학습가이드·내신/수능형)
  - question_bank_items   문제은행(내신형/수능형)
  - question_similar_maps 오답→유사문항 사전매칭(문항당 2개)
  - weakness_check_pdfs   약점체크 PDF 생성 기록
  - workbook_submissions  워크북 사진 업로드·수행도 도장

placeholder — DB 설계 확정 후 모델 정의.
"""
from django.db import models  # noqa: F401

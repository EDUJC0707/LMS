"""boards 도메인 — 게시판·문의·상담 (DB 설계 도메인 7).

정렬 테이블:
  - posts                    게시판(공지/정오표/질답/자유/이벤트굿즈, 주차공지 연동)
  - post_comments            게시판 답글/댓글
  - inquiries · inquiry_messages   1:1 문의 스레드
  - absence_counselings      결석 전화상담 기록(관리자용)
  - parent_counsel_requests  학부모 상담 신청

placeholder — DB 설계 확정 후 모델 정의.
"""
from django.db import models  # noqa: F401

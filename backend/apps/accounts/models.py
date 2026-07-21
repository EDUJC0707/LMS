"""accounts 도메인 — 계정·학생·학부모·RBAC (DB 설계 도메인 1).

정렬 테이블(docs/db/lms-db-design-2026-07-15.md):
  - users            로그인 계정. role: 대표/관리자/조교/학생/학부모
  - students         학생·원번(허브). enrollment_status: 예비등록/등록/퇴원
  - parents          학부모 로그인 계정(연락처 → 계정 승격)
  - parent_students  학부모↔자녀 M:N 연동(다자녀 드롭다운)

스키마 미확정 구간이라 실제 모델은 아직 두지 않는다(placeholder).
DB 설계 확정 후 이 파일에 모델을 정의한다.
"""
from django.db import models  # noqa: F401  (모델 정의 시 사용)

# 예) class Student(models.Model): ...  ← DB 설계 확정 후 추가

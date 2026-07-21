"""videos 도메인 — 복습영상·동보(동영상 보강) (DB 설계 도메인 4).

정렬 테이블:
  - videos          복습영상 마스터
  - video_requests  영상 지급 요청. source: 학생신청/출석자동/동보
                    (유튜브 계정 권한 부여/삭제는 수동 — grant 흐름만 기록)
  - makeup_grants   동보 기록(결석 → 상담 → 동보 → 수강료 체인)

placeholder — DB 설계 확정 후 모델 정의.
"""
from django.db import models  # noqa: F401

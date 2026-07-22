"""동보 지급 체인 공용 서비스 (PRD 3.2.3, MakeupGrant 모델 계약).

MakeupGrant 가 `지급완료` 로 전이될 때 VideoGrant(source=동보) 를 생성하는
지급 체인의 **단일 구현**이다. 두 경로가 공유한다:
  - 관리자 체크(1차 경로) — grades.attendance_admin.grant_makeup (3차 슬라이스)
  - 신청 승인(예비 경로) — videos.views 관리자 approve (4차 슬라이스)

호출측 계약:
  - 트랜잭션은 호출측이 소유한다(출결·신청 상태 갱신과 같은 트랜잭션).
  - 결석 근거(attendance)와 그 회차의 course_week 존재는 호출측이 검증해 둔다.
  - now 는 호출측 기준 시각(요청당 1회 고정 — Asia/Seoul 의미론 선례).

중복 백스톱: 부분 UQ(uq_video_grants_makeup)가 동보 1건당 지급 1건을 DB
레벨에서 최종 방어한다(호출측 선재 검사 + UQ 이중 방어 — 3차 슬라이스 선례).
"""
import datetime

from .models import MakeupGrant, VideoGrant

# 시청 기간 기본 7일(PRD 3.1.4 ⑥) — 관리자 설정화 전까지의 앱 레이어 기본값.
# 출석자동(attendance_admin)·동보 지급이 공유하는 단일 기본값.
GRANT_DURATION = datetime.timedelta(days=7)


def complete_makeup(makeup, actor, now):
    """makeup 을 `지급완료` 로 전이하고 VideoGrant(동보) 를 생성해 반환한다.

    출석생과 동일한 그 주 복습영상 권한(PRD 3.2.3) — 주차는 결석 근거 회차의
    course_week, 만료는 now + GRANT_DURATION.
    """
    makeup.status = MakeupGrant.Status.GRANTED
    makeup.granted_at = now
    makeup.save(update_fields=["status", "granted_at"])
    return VideoGrant.objects.create(
        student_id=makeup.student_id,
        course_week=makeup.attendance.session.course_week,
        source=VideoGrant.Source.MAKEUP,
        makeup=makeup,
        granted_by=actor,
        granted_at=now,
        expires_at=now + GRANT_DURATION,
    )

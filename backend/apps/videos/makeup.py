"""동보 지급 체인 공용 서비스 (PRD 3.2.3, MakeupGrant 모델 계약).

MakeupGrant 가 `지급완료` 로 전이될 때 VideoGrant(source=동보) 를 생성하는
지급 체인의 **단일 구현**이다. 세 경로가 공유한다:
  - 관리자 체크 — grades.attendance_admin.grant_makeup
  - 담임의 `결석(동보)` 입력 — grades.attendance_admin 트리거 ③
  - 학생·학부모 신청 — videos.views (승인 없이 조건이 차면 바로 — FLOW 3-4)

호출측 계약:
  - 트랜잭션은 호출측이 소유한다(출결·신청 상태 갱신과 같은 트랜잭션).
  - 결석 근거(attendance)와 그 회차의 course_week 존재는 호출측이 검증해 둔다.
  - now 는 호출측 기준 시각(요청당 1회 고정 — Asia/Seoul 의미론 선례).

중복 백스톱: 부분 UQ(uq_video_grants_makeup_video)가 **동보 1건 + 영상 1개당
1행**을 DB 레벨에서 최종 방어한다(2026-08-04 지급 단위 개정 — 구 제약은 makeup
단독이었다). 호출측 선재 검사 + UQ 이중 방어(3차 슬라이스 선례).
"""
import datetime

from .models import MakeupGrant, Video, VideoGrant

# 시청 기간 기본 7일(PRD 3.1.4 ⑥) — 관리자 설정화 전까지의 앱 레이어 기본값.
# 출석자동(attendance_admin)·동보 지급이 공유하는 단일 기본값.
GRANT_DURATION = datetime.timedelta(days=7)


def published_videos_of(course_week):
    """그 주차의 `공개` 영상들 — 지급 대상(VideoGrant 지급 시점 계약).

    **공개된 것만** 대상이다. 준비중·아카이브 영상에 권한을 미리 깔면 학생이
    아직 못 볼 영상의 만료가 조용히 흘러간다. 그래서 영상은 출결 입력 전에
    공개돼 있어야 하고, 늦게 공개한 영상은 수동 지급으로 메운다(모델 계약).
    """
    if course_week is None:
        return []
    return list(
        Video.objects.filter(
            course_week=course_week, status=Video.Status.PUBLISHED
        ).order_by("sequence_no", "video_id")
    )


def complete_makeup(makeup, actor, now):
    """makeup 을 `지급완료` 로 전이하고 VideoGrant(동보) 를 만들어 목록을 반환한다.

    출석생과 동일한 그 주 복습영상 권한(PRD 3.2.3) — 결석 근거 회차 주차의
    **공개 영상마다 1행**, 만료는 now + GRANT_DURATION.

    **반환이 단수 → 복수로 바뀌었다**(2026-08-04 지급 단위 개정). 공개 영상이
    하나도 없으면 빈 목록이며, 이때도 makeup 은 `지급완료` 로 전이한다 —
    지급 처리는 끝났고 볼 영상이 아직 없는 것뿐이라 두 사실을 뭉치지 않는다.
    """
    makeup.status = MakeupGrant.Status.GRANTED
    makeup.granted_at = now
    makeup.save(update_fields=["status", "granted_at"])
    videos = published_videos_of(makeup.attendance.session.course_week)
    return VideoGrant.objects.bulk_create(
        [
            VideoGrant(
                student_id=makeup.student_id,
                video=video,
                source=VideoGrant.Source.MAKEUP,
                makeup=makeup,
                granted_by=actor,
                granted_at=now,
                expires_at=now + GRANT_DURATION,
            )
            for video in videos
        ]
    )

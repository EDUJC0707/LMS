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


def held_video_ids(student_ids, videos, now, exclude_attendances=()):
    """지금 살아있는 권한으로 이미 갖고 있는 (student_id, video_id) 집합.

    **같은 영상을 두 번 주지 않는다**(FLOW 3-5). 이미 가진 학생은 건너뛰므로
    만료는 **처음 준 시점 + 일주일** 그대로다 — 새 행을 만들면 그 행의 만료가
    일주일 뒤로 다시 잡혀 시청 기간이 조용히 늘어난다. 출석 자동지급·동보·현보가
    같은 주차 영상에서 겹치는 자리가 있어(한 학생이 같은 주차 회차를 둘 이상
    갖는 경우) 지급 단위가 아니라 **학생×영상**으로 봐야 걸린다.

    회수된 권한은 `active()` 밖이라 여기 안 잡힌다 — 정정으로 껐다 켜는 재활성은
    이 규칙의 대상이 아니다(attendance_admin 의 정정 정책).

    `exclude_attendances` 는 **지금 처리 중인 출결**들이다. 그 출결을 근거로
    (직접 또는 동보를 거쳐) 매달린 권한은 이 저장이 스스로 켜고 끄는 것이라
    "이미 가진 것"으로 세지 않는다 — 세면 출석 ↔ 동보 정정이 서로를 막는다.
    같은 출결의 자동지급·동보 권한이 동시에 살아 있지 않도록 하는 일은 부분 UQ 와
    회수 로직이 이미 하고 있고, 이 함수가 보는 것은 **다른 근거로 이미 나간 권한**이다.
    """
    if not videos or not student_ids:
        return set()
    rows = VideoGrant.objects.active(now).filter(
        student_id__in=student_ids, video__in=videos
    )
    if exclude_attendances:
        rows = rows.exclude(attendance_id__in=exclude_attendances).exclude(
            makeup__attendance_id__in=exclude_attendances
        )
    return set(rows.values_list("student_id", "video_id"))


def complete_makeup(makeup, actor, now):
    """makeup 을 `지급완료` 로 전이하고 VideoGrant(동보) 를 만들어 목록을 반환한다.

    출석생과 동일한 그 주 복습영상 권한(PRD 3.2.3) — 결석 근거 회차 주차의
    **공개 영상마다 1행**, 만료는 now + GRANT_DURATION.

    **반환이 단수 → 복수로 바뀌었다**(2026-08-04 지급 단위 개정). 공개 영상이
    하나도 없으면 빈 목록이며, 이때도 makeup 은 `지급완료` 로 전이한다 —
    지급 처리는 끝났고 볼 영상이 아직 없는 것뿐이라 두 사실을 뭉치지 않는다.
    이미 가진 영상을 건너뛰어 0건이 되는 경우도 같다(held_video_ids).
    """
    makeup.status = MakeupGrant.Status.GRANTED
    makeup.granted_at = now
    makeup.save(update_fields=["status", "granted_at"])
    videos = published_videos_of(makeup.attendance.session.course_week)
    held = held_video_ids(
        [makeup.student_id], videos, now, exclude_attendances=[makeup.attendance_id]
    )
    videos = [v for v in videos if (makeup.student_id, v.video_id) not in held]
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

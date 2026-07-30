"""복습영상 재생 서비스 — 권한 강제 + 서버 워터마크 조립 (PRD 3.1.3/3.1.4·§4).

재생 화면이 부르는 단 하나의 진입점(`build_playback`)이다. "볼 수 있는가"의
판정과 "무엇을 찍는가"의 조립을 여기서 끝내고, 뷰는 None → 404 매핑만 한다.

**권한 원천은 `VideoGrant` 하나다.** `MakeupGrant` 는 동보 신청·승인의 서류이지
권한이 아니다 — 7일 만료(`expires_at`)도 회수(`revoked_at`)도 VideoGrant 에만
있고, 출결 정정 시 실제로 권한을 끄는 것도 attendance_admin 이 VideoGrant 를
revoke 하는 쪽이다(makeup.complete_makeup 이 `지급완료` 전이에서 VideoGrant(동보)
를 만들어 두 경로가 여기서 합류한다). MakeupGrant 를 보고 판정하면 만료·회수가
통째로 무시된다. 그래서 진입은 `VideoGrant.objects.active()` 단 하나다
(VideoGrant 모델 docstring 의 "소비자용 API 유일 진입" 계약).

**이중 게이트**: `Video.status == 공개` + 활성 권한. 지급 단위는 주차라
영상의 `course_week` 와 권한의 `course_week` 가 같아야 한다. 주차 없는 특강은
지급 단위가 없어 권한이 성립하지 않는다(= 못 본다).

**차단은 404**: 권한 밖 video_id 는 영상이 있든 없든, 준비중이든 아카이브든
똑같이 "찾을 수 없습니다" 다. 403 으로 갈리면 "그 번호의 영상은 존재한다"가
새어 나간다(§4 상태 기반 노출 — clinic 소유 밖 404·성적표 404 선례와 동일).

**워터마크를 왜 서버가 만드는가**: DRM(Mux, 런칭 직전 도입 — docs/decisions.md
§3)은 **파일 다운로드**를 막는다. 그러면 유출 경로가 **화면 녹화** 하나로 좁아지고,
녹화본에는 이 워터마크가 그대로 찍힌다. 둘은 대체재가 아니라 서로 다른 구멍을
막는다 — DRM 없이 워터마크만 있으면 파일을 통째로 받아가면 그만이라 소용이 없고,
워터마크 없이 DRM 만 있으면 녹화본이 누구 것인지 알 수 없다.
그래서 값은 **로그인 세션의 학생**에서 서버가 뽑고, 시청 날짜도 **서버 시계
Asia/Seoul** 로 찍는다. 클라이언트가 자기 프로필·기기 시계로 조립하면
개발자도구로 남의 이름·다른 날짜로 바꿔치기할 수 있어 유출 추적이 무너진다.
"""
from django.utils import timezone

from .models import Video, VideoGrant

# 워터마크 조각 구분자 — `고2 · 김하늘 · 2026-07-30`
WATERMARK_SEPARATOR = " · "


def build_watermark(student, watched_on):
    """`{학년} · {이름} · {시청 날짜}` 완성 문자열을 만든다.

    **조각이 아니라 완성 문자열을 내리는 이유**: 조각을 내리면 프런트가 다시
    조립하게 되고, 그 순간 순서·구분자·누락이 화면마다 갈린다. 날짜가 빠진
    워터마크는 "언제 샜는지"를 잃어 절반이 무의미해지므로 무엇을 어떤 순서로
    찍을지는 보안 결정이고, 결정은 한 곳(서버)에 있어야 한다. 화면은 이 문자열을
    그대로 그린다.

    학년이 비어 있으면(관리자 입력 메타 — 학생 잘못이 아니다) 재생을 막지 않고
    그 조각만 뺀다. 구분자를 고정 문자열로 이어 붙이면 ` · 김하늘 · …` 처럼
    앞이 뜬 워터마크가 나온다.
    """
    pieces = [
        (student.grade or "").strip(),
        (student.user.name if student.user else "").strip(),
        watched_on.isoformat(),
    ]
    return WATERMARK_SEPARATOR.join(piece for piece in pieces if piece)


def build_playback(student, video_id, now):
    """재생 페이로드를 만든다. 볼 자격이 없으면 None(호출측이 404 로 매핑).

    - student: 로그인 세션에서 해석된 본인(호출측이 user 를 select_related).
    - now: 기준 시각. 권한 활성 판정과 시청 날짜가 **같은 한 시각**을 쓴다.
    """
    video = (
        Video.objects.select_related("course_week__course")
        .filter(
            pk=video_id,
            status=Video.Status.PUBLISHED,
            course_week__isnull=False,
        )
        .first()
    )
    if video is None:
        return None
    grant = (
        VideoGrant.objects.active(at=now)
        .filter(student=student, course_week=video.course_week)
        .order_by("-expires_at")  # 재지급이 겹치면 늦게 끝나는 권한이 기준
        .first()
    )
    if grant is None:
        return None
    week = video.course_week
    return {
        "video": {
            "video_id": video.video_id,
            "title": video.title,
            "sequence_no": video.sequence_no,
            "duration_seconds": video.duration_seconds,
            # 업체 미정 — provider·external_ref 를 그대로 내리고 재생기가
            # 해석한다(Provider 중립 계약, Video 모델 docstring)
            "provider": video.provider,
            "external_ref": video.external_ref,
            "course_name": week.course.name,
            "week_no": week.week_no,
        },
        "watermark": build_watermark(student, timezone.localdate(now)),
        "expires_at": timezone.localtime(grant.expires_at).isoformat(),
    }

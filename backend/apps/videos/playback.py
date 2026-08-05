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

**이중 게이트**: `Video.status == 공개` + 그 **영상에 대한** 활성 권한.
지급 단위가 영상이라(2026-08-04 개정) 판정은 `권한.video == 영상` 직접 조인이다 —
구 설계처럼 주차를 맞춰 보지 않는다. 그래서 관리자가 영상의 주차를 옮겨도 이미
지급된 권한은 끊기지 않는다.

주차 없는 특강도 **권한만 있으면 볼 수 있다**(수동 지급 경로). 출결 자동지급은
주차를 축으로 대상을 고르므로 특강에 자동으로 나지 않을 뿐이다 — "지급이 안 난다"와
"보면 안 된다"는 다른 말이라 재생을 막지 않는다. 주차에서 오는 표시값
(강좌명·주차번호)은 그때 비어 나간다.

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
from django.conf import settings
from django.utils import timezone

from . import mux
from .models import Video, VideoGrant

#: 시드가 넣는 가짜 참조의 접두 — 실제 자산이 아니라는 표시(seed_demo.py).
SEED_REF_PREFIX = "seed-"


def resolve_ref(video):
    """(재생 참조, Mux 자산인가) — 시드용 가짜 값이면 데모 자산으로 바꾼다.

    **대체와 서명이 반드시 같은 자리에 있어야 한다.** 프런트가 갈아치우면
    서명은 `seed-1-1` 앞으로 나가고 재생은 다른 자산이 되어 Mux 가 거부한다
    ("playback-token formatted with incorrect information" — 2026-08-04 실측).
    그래서 판정을 여기 하나로 모은다.

    설정이 비어 있으면 그대로 둔다 — 운영에는 시드 데이터가 없고, 조용히
    다른 영상을 틀어 주는 것보다 재생이 실패하는 편이 낫다.

    **"Mux 인가" 를 모델의 `provider` 가 아니라 여기서 함께 돌려주는 이유**:
    대체가 일어나면 실제로 재생되는 것은 **데모 자산(= Mux)** 인데 모델의
    provider 는 비어 있을 수 있다(연동 전 영상). 그때 provider 로 판정하면
    참조는 대체됐는데 **토큰은 안 나가** 서명 자산이 403 이 된다
    (2026-08-04 관리자 미리보기에서 실측). 판정을 대체와 같은 자리에 둔다.
    """
    external_ref = video.external_ref
    demo = (getattr(settings, "MUX_DEMO_PLAYBACK_ID", "") or "").strip()
    if demo and (not external_ref or external_ref.startswith(SEED_REF_PREFIX)):
        return demo, True  # 데모 자산은 우리 Mux 계정의 것이다
    return external_ref, video.provider == Video.Provider.MUX

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


def build_preview(video, actor, now):
    """관리자 미리보기 — **상태·권한을 보지 않는다.**

    관리 화면에서 등록한 영상이 실제로 재생되는지 확인할 수단이 없었다.
    소비자 재생 API 는 `IsStudent` + 활성 권한 이중 게이트라 대표·관리자
    계정으로는 절대 열리지 않는다. 그래서 관리자가 넣은 참조가 틀렸는지는
    **학생 문의로만** 드러났다(2026-08-04).

    **소비자 판정을 재사용하지 않는 이유**: 미리보기의 목적은 `준비중` 영상을
    공개 전에 확인하는 것이다. `build_playback` 을 부르면 그 이중 게이트에
    걸려 정확히 확인하고 싶은 것을 못 본다. 대신 **접근 통제는 뷰의 기능 게이트**
    (`영상지급관리`)가 진다 — 여기에는 게이트가 없으므로 호출측이 반드시 건다.

    워터마크는 **직원 본인** 이름으로 찍는다. 학생 것으로 찍으면 미리보기 화면이
    유출됐을 때 엉뚱한 학생이 지목된다.
    """
    ref, is_mux = resolve_ref(video)
    week = video.course_week
    return {
        "video": {
            "video_id": video.video_id,
            "title": video.title,
            "sequence_no": video.sequence_no,
            "duration_seconds": video.duration_seconds,
            "provider": video.provider,
            "external_ref": ref,
            "tokens": mux.playback_tokens(ref, now) if is_mux else {},
            "course_name": week.course.name if week else None,
            "week_no": week.week_no if week else None,
        },
        "watermark": build_staff_watermark(actor, timezone.localdate(now)),
        "viewer_id": str(actor.pk),
    }


def build_staff_watermark(user, watched_on):
    """`{역할} · {이름} · {날짜}` — 학생 워터마크와 같은 자리 배치."""
    pieces = [
        (getattr(user, "role", "") or "").strip(),
        (getattr(user, "name", "") or "").strip(),
        watched_on.isoformat(),
    ]
    return WATERMARK_SEPARATOR.join(piece for piece in pieces if piece)


def build_playback(student, video_id, now):
    """재생 페이로드를 만든다. 볼 자격이 없으면 None(호출측이 404 로 매핑).

    - student: 로그인 세션에서 해석된 본인(호출측이 user 를 select_related).
    - now: 기준 시각. 권한 활성 판정과 시청 날짜가 **같은 한 시각**을 쓴다.
    """
    grant = (
        VideoGrant.objects.active(at=now)
        .select_related("video__course_week__course")
        .filter(student=student, video_id=video_id, video__status=Video.Status.PUBLISHED)
        .order_by("-expires_at")  # 재지급이 겹치면 늦게 끝나는 권한이 기준
        .first()
    )
    if grant is None:
        return None
    video = grant.video
    # 주차 없는 특강 — 권한이 영상을 직접 가리키므로 재생은 성립한다.
    # 표시값만 비운다(build_video_list 와 같은 판단 — 두 경로가 갈리면
    # "목록엔 있는데 누르면 500" 이 난다).
    ref, is_mux = resolve_ref(video)
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
            "external_ref": ref,
            # 서명 정책 영상은 토큰 없이는 403 이다. 발급은 서버 몫 —
            # 개인키가 프런트로 나가면 누구나 자기 토큰을 찍을 수 있다.
            # 위 `ref` 로 서명한다 — 대체된 값과 같아야 Mux 가 받는다.
            "tokens": mux.playback_tokens(ref, now) if is_mux else {},
            "course_name": week.course.name if week else None,
            "week_no": week.week_no if week else None,
        },
        "watermark": build_watermark(student, timezone.localdate(now)),
        # Mux Data 의 시청자 축 — 유출 시 "누가 재생했나"를 되짚는다.
        # 이름이 아니라 **내부 번호**를 쓴다: 업체 분석 화면에 실명을 흘리지 않고
        # 우리 DB 로만 사람을 되짚는다(Mux 권고 — viewer_user_id 에 PII 금지).
        "viewer_id": str(student.student_id),
        "expires_at": timezone.localtime(grant.expires_at).isoformat(),
    }


def build_video_list(student, now):
    """학생이 **지금 볼 수 있는** 영상 목록 — 재생 화면의 유일한 입구.

    재생 API 는 `video_id` 를 받는데 그 번호를 학생에게 알려 주는 자리가
    없었다(홈 마감 목록은 `grant_id`·주차만 싣는다). 목록이 없으면 재생 화면에
    들어갈 방법 자체가 없다.

    판정은 `build_playback` 과 **같은 두 게이트**(공개 영상 + 활성 권한)를 쓴다 —
    목록과 재생이 다른 기준을 쓰면 "목록엔 있는데 누르면 404" 가 나온다.

    만료가 가까운 것을 먼저 보인다(§3.2.0 마감 우선 배치). 같은 주차면 강 순서.
    """
    grants = (
        VideoGrant.objects.active(at=now)
        .select_related("video__course_week__course")
        .filter(student=student, video__status=Video.Status.PUBLISHED)
        .order_by("expires_at")  # 재지급이 겹치면 먼저 끝나는 쪽이 학생이 볼 마감
    )
    # 같은 영상에 권한이 여러 건이면(출석자동 + 수동 재지급 등) 늦게 끝나는 쪽이
    # 학생이 실제로 볼 수 있는 마감이다 — 영상당 한 줄만 남긴다.
    latest = {}
    for grant in grants:
        current = latest.get(grant.video_id)
        if current is None or grant.expires_at > current.expires_at:
            latest[grant.video_id] = grant
    rows = [
        {
            "video_id": grant.video.video_id,
            "title": grant.video.title,
            "sequence_no": grant.video.sequence_no,
            "duration_seconds": grant.video.duration_seconds,
            "course_name": (
                grant.video.course_week.course.name if grant.video.course_week else None
            ),
            "week_no": grant.video.course_week.week_no if grant.video.course_week else None,
            "expires_at": timezone.localtime(grant.expires_at).isoformat(),
        }
        for grant in latest.values()
    ]
    rows.sort(
        key=lambda row: (
            row["expires_at"],
            row["week_no"] if row["week_no"] is not None else 0,
            row["sequence_no"] if row["sequence_no"] is not None else 0,
        )
    )
    return rows

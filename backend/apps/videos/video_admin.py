"""복습영상 등록·관리 서비스 (PRD 3.1.3, `<도메인>_admin.py` 선례).

재생·권한은 만들어 뒀는데 **영상을 등록하는 자리가 없었다**(2026-08-04 확인 —
`admin.py` 비어 있음, `urls.py` 빈 라우터, 관리 화면 0건). 시드가 만든 데이터로만
재생이 돌던 상태를 여기서 끝낸다.

**관리 경로는 소비자 게이팅을 쓰지 않는다.** 목록·조회는 `Video.objects.all()`
기준이다 — 준비중·아카이브가 안 보이면 등록한 영상을 공개할 방법이 없다.
소비자용 진입(`VideoGrant.objects.active()`)은 학생 API 전용 계약이다.

**공개는 서버가 조건을 강제한다.** `공개` 로 올리려면 두 가지가 갖춰져야 한다:
  ① `course_week` — 지급 단위가 주차라 주차가 없으면 아무에게도 지급되지 않는다
  ② `provider` + `external_ref` — 비면 재생기가 데모 영상으로 떨어져 **학생에게
     엉뚱한 영상이 조용히 나간다**
그리고 **이미 공개된 영상은 그 둘을 다시 비울 수 없다**(PATCH 재검증). 공개
전환만 막고 수정을 열어 두면 같은 구멍이 뒷문으로 열린다.

**지급 시점 계약과의 연결(중요)**: 권한은 출결 확정 시점에 그때 `공개` 인 영상에만
생긴다(VideoGrant 모델 계약). 따라서 **영상 공개는 출결 입력보다 앞서야 한다** —
늦게 공개한 영상은 그 주 출석자에게 자동으로 열리지 않는다.
"""
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.curriculum.models import CourseWeek

from .models import Video

#: 값 없음을 뜻하는 입력(빈 문자열)을 NULL 로 접는 대상 — 폼이 빈 칸을 "" 로 보낸다.
_BLANK = ("", None)

_MAX_TITLE = 200
_MAX_EXTERNAL_REF = 200
#: SmallIntegerField 상한 — 넘기면 DB 가 DataError 로 500 을 낸다(400 이 맞다).
_MAX_SEQUENCE_NO = 32767
_MAX_DURATION = 2147483647


def _iso(value):
    """aware datetime → Asia/Seoul 로컬 ISO 문자열.

    `views._iso` 와 같은 일을 하지만 여기 따로 둔다 — views 가 이 모듈을
    import 하므로 반대로 가져오면 순환 import 다.
    """
    return timezone.localtime(value).isoformat() if value else None


def course_week_block(week):
    """주차 요약 — 목록 행과 선택지 목록이 **같은 모양**을 쓰도록 한 곳에서 만든다."""
    if week is None:
        return None
    return {
        "week_id": week.week_id,
        "week_no": week.week_no,
        "start_date": week.start_date.isoformat() if week.start_date else None,
        "course": {"course_id": week.course.course_id, "name": week.course.name},
    }


def video_row(video):
    """영상 한 줄 — 목록·생성·수정·전환 응답 공용(프런트 재조회 불필요).

    호출측이 `select_related("course_week__course")` 를 걸어 둘 것.
    """
    return {
        "video_id": video.video_id,
        "title": video.title,
        "sequence_no": video.sequence_no,
        "provider": video.provider,
        "external_ref": video.external_ref,
        "duration_seconds": video.duration_seconds,
        "status": video.status,
        "created_at": _iso(video.created_at),
        "course_week": course_week_block(video.course_week),
    }


def _base_queryset():
    return Video.objects.select_related("course_week__course")


def load_video(video_id):
    """관리 대상 1건 — 상태를 가리지 않는다(관리 경로 계약)."""
    return _base_queryset().filter(pk=video_id).first()


def list_videos(status_filter=None, course_week_id=None):
    """관리 목록.

    정렬은 **강좌 → 주차 → 차시** 다. 주차를 1순위로 두면 강좌가 둘 이상일 때
    `A 1주차 / B 1주차 / A 2주차` 로 뒤엉킨다. 주차·차시가 비어 있는 영상
    (특강·미분류)은 뒤로 보낸다 — 빈 값이 위로 올라오면 목록 첫 화면이
    "정리 안 된 것"으로 채워진다.
    """
    queryset = _base_queryset()
    if status_filter:
        queryset = queryset.filter(status=status_filter)
    if course_week_id is not None:
        queryset = queryset.filter(course_week_id=course_week_id)
    return queryset.order_by(
        "course_week__course__name",
        "course_week__week_no",
        "sequence_no",
        "video_id",
    )


def course_week_rows():
    """등록 폼의 주차 선택지 — 주차를 못 고르면 그 영상은 영원히 재생되지 않는다.

    소비자 게이팅(`released()`)을 부르지 않는다. 다음 주 영상을 미리 등록해 두는
    것이 이 화면의 정상 용법이다.
    """
    weeks = CourseWeek.objects.select_related("course").order_by(
        "course__name", "week_no"
    )
    return [course_week_block(week) for week in weeks]


def _parse_int(value, field, limit):
    """(값, 에러) — bool 은 int 의 하위형이라 명시적으로 배제한다."""
    if value in _BLANK:
        return None, None
    if isinstance(value, bool) or not isinstance(value, int):
        return None, f"{field}가 올바르지 않습니다."
    if value < 0 or value > limit:
        return None, f"{field}가 올바르지 않습니다."
    return value, None


def parse_input(data, partial=False):
    """(fields, error) — 인정 키만 걷어 낸다.

    `status` 는 **인정하지 않는다**. 상태 전환은 전용 경로(publish/archive)가
    조건을 강제하므로, 일반 수정으로 우회되면 그 조건이 무의미해진다.
    """
    if not isinstance(data, dict):
        return None, "입력이 올바르지 않습니다."
    fields = {}

    if "title" in data or not partial:
        title = (data.get("title") or "").strip()
        if not title:
            return None, "제목을 입력하세요."
        if len(title) > _MAX_TITLE:
            return None, f"제목이 너무 깁니다({_MAX_TITLE}자)."
        fields["title"] = title

    if "course_week_id" in data:
        raw = data.get("course_week_id")
        if raw in _BLANK:
            fields["course_week"] = None
        else:
            week_id, error = _parse_int(raw, "course_week_id", 2147483647)
            if error:
                return None, error
            week = CourseWeek.objects.filter(pk=week_id).first()
            if week is None:
                # 존재를 특정하지 않는다 — 형식 오류와 같은 문구(§4 존재 비노출)
                return None, "course_week_id가 올바르지 않습니다."
            fields["course_week"] = week

    if "sequence_no" in data:
        value, error = _parse_int(data.get("sequence_no"), "sequence_no", _MAX_SEQUENCE_NO)
        if error:
            return None, error
        fields["sequence_no"] = value

    if "duration_seconds" in data:
        value, error = _parse_int(
            data.get("duration_seconds"), "duration_seconds", _MAX_DURATION
        )
        if error:
            return None, error
        fields["duration_seconds"] = value

    if "provider" in data:
        raw = data.get("provider")
        if raw in _BLANK:
            fields["provider"] = None
        elif raw not in Video.Provider.values:
            return None, "provider 값이 올바르지 않습니다."
        else:
            fields["provider"] = raw

    if "external_ref" in data:
        raw = data.get("external_ref")
        ref = (raw or "").strip() if isinstance(raw, str) else raw
        if ref in _BLANK:
            fields["external_ref"] = None
        elif not isinstance(ref, str):
            return None, "external_ref가 올바르지 않습니다."
        elif len(ref) > _MAX_EXTERNAL_REF:
            return None, f"재생 참조 ID가 너무 깁니다({_MAX_EXTERNAL_REF}자)."
        else:
            fields["external_ref"] = ref

    if partial and not fields:
        return None, "수정할 내용이 없습니다."
    return fields, None


def publish_blocker(video):
    """공개를 막는 사유(없으면 None) — publish 와 수정 재검증이 **같은 판정**을 쓴다.

    두 곳이 각자 판정하면 한쪽만 고쳐져 뒷문이 열린다.
    """
    if video.course_week_id is None:
        return "주차를 먼저 연결해야 공개할 수 있습니다."
    if not video.provider or not video.external_ref:
        return "영상 자산을 먼저 연결해야 공개할 수 있습니다."
    return None


def create_video(fields):
    """(video, error). 상태는 받지 않고 모델 기본값 `준비중` 으로 시작한다."""
    try:
        with transaction.atomic():
            video = Video.objects.create(**fields)
    except IntegrityError:
        # 부분 UQ(provider, external_ref) — 같은 자산의 이중 등록
        return None, "이미 등록된 영상입니다."
    return load_video(video.pk), None


def update_video(video, fields):
    """(video, error).

    **주차 변경은 막지 않는다.** 지급 단위가 영상이 된 뒤로(2026-08-04) 주차를
    옮겨도 이미 지급된 권한은 그 영상에 그대로 붙어 있다 — 끊기지 않는다.
    (구 설계에서는 주차를 옮기면 그 주차 권한자 전원이 못 보게 됐다.)

    다만 **공개 중인 영상의 공개 조건은 되돌릴 수 없다** — 그러면 학생 화면이
    조용히 깨진다.
    """
    for key, value in fields.items():
        setattr(video, key, value)
    if video.status == Video.Status.PUBLISHED:
        blocker = publish_blocker(video)
        if blocker is not None:
            return None, "공개 중인 영상은 주차·영상 자산을 비울 수 없습니다."
    try:
        with transaction.atomic():
            video.save()
    except IntegrityError:
        return None, "이미 등록된 영상입니다."
    return load_video(video.pk), None


def publish(video):
    """(video, error) — 학생 노출의 유일한 스위치."""
    if video.status == Video.Status.PUBLISHED:
        return None, "이미 공개된 영상입니다."
    blocker = publish_blocker(video)
    if blocker is not None:
        return None, blocker
    video.status = Video.Status.PUBLISHED
    video.save(update_fields=["status"])
    return load_video(video.pk), None


def archive(video):
    """(video, error) — 내리는 유일한 수단(물리 삭제 없음, PRD 8-16).

    **VideoGrant 는 한 행도 건드리지 않는다.** 권한 이력은 감사 기록이고,
    학생 노출은 재생 판정의 `status=공개` 게이트가 이미 막는다.
    """
    if video.status == Video.Status.ARCHIVED:
        return None, "이미 보관한 영상입니다."
    video.status = Video.Status.ARCHIVED
    video.save(update_fields=["status"])
    return load_video(video.pk), None

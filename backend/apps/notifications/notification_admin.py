"""관리자 발송내역 조회 — 필터 해석·행 조립 (PRD 3.1.2).

**이 조회가 없으면 발송 실패가 보이지 않는다.** 발송 경로는 실패 사유를
`error_msg` 에 남기고 재발송 배치가 다시 집어가지만, 그 사유를 꺼내는 자리가
없으면 "안 나갔다"는 사실 자체를 아무도 모른다. 그래서 응답의 중심은 목록이
아니라 **status + error_msg** 다.

필터 해석은 여기서 끝낸다(뷰는 게이트·상태 코드 매핑만 — clinic_admin 선례).
값집합 밖 입력은 빈 목록이 아니라 **오류**다: `status=성공함` 같은 오타가 빈
목록으로 돌아오면 "발송이 하나도 없다"로 읽혀 정반대의 판단을 부른다.

**`type` 만은 검증하지 않는다.** 개방 값집합(8-17 미결)이라 값집합을 걸면 새
발송 유형이 추가되는 순간 조회가 막힌다 — 모델이 choices 를 필드에 바인딩하지
않은 것과 같은 이유다.

**기간은 `created_at` 축이다.** `sent_at` 은 미발송·실패 행에서 NULL 이라 범위
필터에 쓰면 정작 찾아야 할 실패 건이 통째로 빠진다.
"""
import datetime

from django.utils import timezone

from .models import Notification


class NotificationQueryError(Exception):
    """필터 입력 오류 — message 를 뷰가 400 본문으로 옮긴다(ClinicError 선례)."""

    def __init__(self, message):
        super().__init__(message)
        self.message = message


def build_queryset(params):
    """조회 파라미터 → 정렬된 queryset. 잘못된 값은 `NotificationQueryError`."""
    queryset = Notification.objects.select_related("student__user", "parent", "user")

    status = params.get("status")
    if status:
        _require_choice(status, Notification.Status, "상태")
        queryset = queryset.filter(status=status)

    channel = params.get("channel")
    if channel:
        _require_choice(channel, Notification.Channel, "채널")
        queryset = queryset.filter(channel=channel)

    # type 은 검증하지 않는다 — 개방 값집합(위 docstring).
    notif_type = params.get("type")
    if notif_type:
        queryset = queryset.filter(type=notif_type)

    student_id = _parse_id(params.get("student_id"), "student_id")
    if student_id is not None:
        queryset = queryset.filter(student_id=student_id)

    parent_id = _parse_id(params.get("parent_id"), "parent_id")
    if parent_id is not None:
        queryset = queryset.filter(parent_id=parent_id)

    date_from = _parse_date(params.get("from"), "from")
    if date_from is not None:
        queryset = queryset.filter(created_at__gte=_start_of(date_from))

    date_to = _parse_date(params.get("to"), "to")
    if date_to is not None:
        # 끝 날짜는 그날을 포함한다 — 관리자가 오늘까지 보려고 오늘을 적는다.
        queryset = queryset.filter(created_at__lt=_start_of(date_to + datetime.timedelta(days=1)))

    # -notif_id 로 정렬한다(MeNotificationsView 와 같은 축) — sent_at 은 미발송
    # 행에서 NULL 이라 최신순이 성립하지 않는다.
    return queryset.order_by("-notif_id")


def build_row(notification):
    return {
        "notif_id": notification.notif_id,
        "target": _target(notification),
        "type": notification.type,
        "channel": notification.channel,
        "status": notification.status,
        "title": notification.title,
        "body": notification.body,
        "error_msg": notification.error_msg,
        "ref_type": notification.ref_type,
        "ref_id": notification.ref_id,
        "sent_at": _localized(notification.sent_at),
        "created_at": _localized(notification.created_at),
    }


def _target(notification):
    """대상 3분기 → 표시용 한 덩어리. 셋 중 하나만 채워져 있다(모델 clean 계약)."""
    if notification.student_id:
        student = notification.student
        # students 에 name 컬럼이 없다 — 이름은 users 행이 든다. 계정 발급 전이면
        # 비어 있으므로 원번으로 떨어진다(관리자가 지면에서 쓰는 값).
        name = student.user.name if student.user else ""
        return {
            "kind": "학생",
            "id": notification.student_id,
            "name": name or student.unique_id,
        }
    if notification.parent_id:
        parent = notification.parent
        return {
            "kind": "학부모",
            "id": notification.parent_id,
            "name": parent.name or parent.phone,
        }
    if notification.user_id:
        return {"kind": "직원", "id": notification.user_id, "name": notification.user.name}
    return None


def _require_choice(value, choices, label):
    if value not in set(choices.values):
        raise NotificationQueryError(f"{label} 값이 올바르지 않습니다.")


def _parse_id(raw, label):
    if raw in (None, ""):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise NotificationQueryError(f"{label} 값이 올바르지 않습니다.") from None


def _parse_date(raw, label):
    if raw in (None, ""):
        return None
    try:
        return datetime.date.fromisoformat(raw)
    except ValueError:
        raise NotificationQueryError(f"{label} 날짜 형식이 올바르지 않습니다.") from None


def _start_of(day):
    """그 날 00:00(Asia/Seoul) — 서버 시계 기준으로 하루 경계를 잡는다."""
    return timezone.make_aware(datetime.datetime.combine(day, datetime.time.min))


def _localized(value):
    return timezone.localtime(value).isoformat() if value else None

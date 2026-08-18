"""클리닉 관리자 서비스 — 배정·출결·노쇼 밴·평가 (PRD 3.2.4 관리자 측).

규칙 강제 지점(booking.py 와 같은 구조 — ClinicError 재사용):
  ① 승인+배정: `대기`→`승인배정`. **재배정 허용**(`승인배정` 상태에서 담당·링크
     교체) — 수업 당일 현장 대응 불가 전제라 조교 사정 변경 시 수동 우회가
     있어야 한다(key_considerations §5). 화상 링크는 **서버가 만든다** —
     `conferencing.get_adapter()` 로 스페이스 1개를 새로 뚫고 provider·ref·url
     셋을 함께 저장한다(링크 재사용 금지가 사람의 손버릇이 아니라 코드가 된다).
     관리자가 링크를 직접 넘기면 그것이 이기고 업체 호출은 없다 — 연동이
     끊긴 날에도 배정이 성립해야 한다(§5 수동 우회).
  ② 출결 처리: `승인배정` + 미처리 건만. **재처리 400** — 결석 재처리를
     허용하면 noshow_count 가 이중 집계된다. 정정이 필요하면 대표가 unban
     으로 풀고 재집계하는 수동 절차(파괴적 정정 자동화 금지 — §5).
  ③ 노쇼: 결석 = noshow_count +1, **2회 도달 시 clinic_banned=true**
     (원천은 accounts.Student — ClinicRequest 모델 계약, 사본 금지).
     **판정은 언제나 사람이 한다**(2026-08-04 확정). 화상 업체가 참가자
     입·퇴장 시각을 내주므로 "시작 10분 이상 미출석"을 기계가 계산할 수는
     있다(실측 확인). 그래도 자동으로 찍지 않는다 — 노쇼 2회면 영구제한이고
     그건 파괴적 처분이라 사람 손을 거쳐야 한다(§5). 접속 불량·조교 지각처럼
     기록만 봐서는 갈리지 않는 사정도 조교만 안다. 자동 판정을 넣고 싶어지면
     **판정이 아니라 참고 표시**까지가 한계다.
  ④ 해제(unban): **대표 전용** — 노쇼 영구제한 해제는 key_considerations §2
     의 대표 전용 민감 기능 후보라서 범위 확정 전까지 가장 좁게(대표만) 연다
     (닫힘이 안전 기본값 — §5). noshow_count 는 유지 — 누적은 사실 기록이고,
     해제 후 재노쇼 시 즉시 재제한되는 것이 의도된 동작이다.

알림(출석/결석 → 학부모, 노쇼 경고 → 학생·학부모 — PRD 3.2.4)은
`notifications.sending.queue` 로 건다 — 행을 남기고 **커밋 뒤** 발송 태스크가
걸린다(2026-08-04 발송 파이프라인 도입 전까지는 행 기록만 하고 배치를 기다렸다).
채널 구현체가 없거나 실패하면 사유가 행에 남고 재발송 배치가 다시 집는다.
"""
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.accounts.models import ParentStudent
from apps.accounts.permissions import STAFF_ROLES
from apps.notifications.models import Notification
from apps.notifications.sending import queue as queue_notification

from .booking import ClinicError
from .conferencing import (
    Conference,
    ConferenceError,
    PermanentConferenceError,
    TemporaryConferenceError,
    get_adapter,
)
from .models import (
    ClinicEvalCriteria,
    ClinicEvaluation,
    ClinicEvaluationItem,
    ClinicRequest,
)

# 노쇼 영구제한 임계값(PRD 3.2.4 — 누적 2회). 컷값 변경은 대표 전용 후보라
# 설정화(관리자 화면)는 후순위 — 코드 상수로 시작한다.
NOSHOW_BAN_THRESHOLD = 2


# --- 대기열 조회 ----------------------------------------------------------


#: `period` 값집합 — 대기열은 앞을 보고(배정할 것) 지난 목록은 뒤를 본다(결과).
PERIOD_PAST = "지난"
PERIOD_UPCOMING = "예정"
PERIODS = (PERIOD_PAST, PERIOD_UPCOMING)


def queue_rows(status_filter=None, date_filter=None, period=None):
    """신청 대기열 — 학생 노쇼·제한 상태 동봉(배정 판단 자료).

    `period` 는 오늘을 기준으로 가른다. 오늘 것은 **예정** 쪽이다 — 아직 안 끝난
    수업을 '지난' 목록에 올리면 결과가 비어 있는 게 정상인데 빠뜨린 것처럼 보인다.
    """
    qs = (
        ClinicRequest.objects.select_related("student__user", "assigned_staff", "slot")
        .select_related("evaluation")
        .order_by("requested_date", "requested_time", "clinic_id")
    )
    if status_filter:
        qs = qs.filter(status=status_filter)
    if date_filter:
        qs = qs.filter(requested_date=date_filter)
    if period == PERIOD_PAST:
        qs = qs.filter(requested_date__lt=timezone.localdate()).order_by(
            "-requested_date", "-requested_time", "-clinic_id"
        )
    elif period == PERIOD_UPCOMING:
        qs = qs.filter(requested_date__gte=timezone.localdate())
    return [queue_row(r) for r in qs]


def queue_row(request):
    student = request.student
    return {
        "clinic_id": request.clinic_id,
        "student": {
            "student_id": student.student_id,
            "name": student.user.name if student.user else None,
            "login_id": student.user.login_id if student.user else None,
            "matching_key": student.matching_key,
            "noshow_count": student.noshow_count,
            "clinic_banned": student.clinic_banned,
        },
        "exam_id": request.exam_id,
        "slot_id": request.slot_id,
        "requested_date": request.requested_date.isoformat(),
        "requested_time": request.requested_time.strftime("%H:%M"),
        "status": request.status,
        "assigned_staff": (
            {"user_id": request.assigned_staff.user_id, "name": request.assigned_staff.name}
            if request.assigned_staff
            else None
        ),
        "conference_url": request.conference_url,
        "attendance_status": request.attendance_status,
        "supervision": _supervision_block(request),
    }


def _supervision_block(request):
    """수집된 감독 자료(요약·문서 링크). 아직 없으면 None.

    **None 과 빈 요약은 다른 사실이다.** None 은 가져올 회의 자료가 아예 없다는
    뜻이고(아무도 안 들어왔거나 조교가 전사가 안 되는 기기로 호스트했거나),
    요약만 비어 있으면 문서는 있는데 잘라낼 자리를 못 찾은 것이다. 화면이 그
    둘을 구분해 말할 수 있어야 조교가 평가를 안 한 것처럼 보이지 않는다.
    """
    evaluation = getattr(request, "evaluation", None)
    if evaluation is None or not evaluation.transcript_url:
        return None
    return {
        "summary": evaluation.ai_summary,
        "transcript_url": evaluation.transcript_url,
    }


# --- 승인·배정 ------------------------------------------------------------

_ASSIGNABLE = (ClinicRequest.Status.PENDING, ClinicRequest.Status.APPROVED)


def assign(request, staff_user):
    """승인+배정(①) — 담당 직원·화상 링크를 걸고 `승인배정`으로 전이.

    링크가 정해지는 순서:
      1. 이미 링크가 있다(재배정) → **그대로 둔다**. 클리닉 1건 = 스페이스 1개
         (§4)이고, 조교만 바뀌는데 링크가 갈리면 학생이 이미 받은 링크가 죽는다.
         시간이 바뀐 경우는 `booking.change_booking` 이 셋을 비워 두므로 여기서
         새로 뚫린다.
      2. 없다 → 화상 어댑터로 **새 스페이스 1개**를 만든다.

    ~~관리자가 링크를 손으로 넣는 경로~~ 는 없앴다(2026-08-18). 실제로 그렇게
    배정하는 상황이 없는데 코드 경로만 하나 더 있었고, 그 경로로 들어온 건은
    `conference_ref` 가 비어 감독 자료를 못 거두는 반쪽 상태가 됐다.

    **실패하면 아무것도 바꾸지 않는다.** 스페이스를 먼저 만들고 그 다음에
    필드를 건드리는 순서인 이유다 — `승인배정`인데 링크가 없는 행은 학생에게
    빈 안내가 되고, 출결 처리까지 열려 버린다(mark_attendance 는 `승인배정`만
    받는다).
    """
    if request.status not in _ASSIGNABLE:
        raise ClinicError("배정할 수 없는 상태입니다.")
    if staff_user is None or staff_user.role not in STAFF_ROLES or not staff_user.is_active:
        raise ClinicError("배정 대상은 활성 직원이어야 합니다.")
    conference = _resolve_conference(request)
    request.status = ClinicRequest.Status.APPROVED
    request.assigned_staff = staff_user
    request.conference_provider = conference.provider
    request.conference_ref = conference.ref
    request.conference_url = conference.url
    request.save(
        update_fields=[
            "status",
            "assigned_staff",
            "conference_provider",
            "conference_ref",
            "conference_url",
        ]
    )
    _book_supervision(request)
    return request


def supervision_key(request):
    """감독 예약을 다시 가리키는 이름 — 클리닉 1건에 하나, 바뀌지 않는다.

    시각이 바뀌어도 같은 이름이라 예약이 덮어써진다. 어느 예약이 그 클리닉
    것인지 적어 둘 컬럼이 필요 없는 이유다.
    """
    return f"clinic{request.clinic_id}"


def _book_supervision(request):
    """끝난 배정에 감독을 걸어 둔다. **실패해도 배정은 되돌리지 않는다.**

    감독은 다음에 다시 걸 수 있지만 배정은 사람이 다시 해야 한다 — 업체 장애로
    관리자의 작업이 통째로 날아가는 편이 훨씬 나쁘다. 못 건 예약은 그 회차의
    감독 자료가 없다는 뜻이고, 그건 화면이 이미 "자료 없음"으로 말한다.
    """
    from . import supervision

    try:
        get_adapter().schedule_supervision(
            request.conference_url,
            key=supervision_key(request),
            title=supervision.artifact_path(request),
            starts_at=supervision.starts_at(request),
            minutes=supervision.slot_minutes(request),
        )
    except ConferenceError:
        return


def _resolve_conference(request):
    """배정에 쓸 화상 3열을 정한다(위 순서 1·2). 실패는 ClinicError."""
    if request.conference_url:
        return Conference(
            provider=request.conference_provider,
            ref=request.conference_ref,
            url=request.conference_url,
        )
    try:
        return get_adapter().create_space()
    except TemporaryConferenceError as error:
        # 다시 걸면 될 수 있다 — 관리자가 버튼을 한 번 더 누르면 되는 상황
        raise ClinicError(str(error), http_status=503) from error
    except PermanentConferenceError as error:
        # 자격증명 없음·스코프 미승인 — 재시도로는 안 풀린다. 사유를 그대로
        # 올려 보낸다: 감추면 관리자는 왜 배정이 안 되는지 알 길이 없다.
        raise ClinicError(str(error)) from error


def reject(request):
    """미승인 — `대기` 건만."""
    if request.status != ClinicRequest.Status.PENDING:
        raise ClinicError("미승인 처리할 수 없는 상태입니다.")
    request.status = ClinicRequest.Status.REJECTED
    request.save(update_fields=["status"])
    return request


# --- 출결 처리·노쇼 -------------------------------------------------------


def mark_attendance(request, value, actor):
    """출석/결석 처리(②③) — 노쇼 누적·밴·알림 행 기록을 한 트랜잭션으로.

    원자성 판단: 출결 스탬프와 noshow_count/clinic_banned 는 원천-파생 관계
    (attendance_admin 의 SSOT-트리거 판단과 동일) — 부분 성공을 남기지 않는다.
    """
    if request.status != ClinicRequest.Status.APPROVED:
        raise ClinicError("승인배정된 건만 출결 처리할 수 있습니다.")
    if request.attendance_status in (
        ClinicRequest.AttendanceStatus.PRESENT,
        ClinicRequest.AttendanceStatus.ABSENT,
    ):
        raise ClinicError("이미 출결 처리된 건입니다.")  # 재처리 = 노쇼 이중 집계 위험
    now = timezone.now()
    student = request.student
    parents = [link.parent for link in ParentStudent.objects.filter(student=student)]
    with transaction.atomic():
        request.attendance_status = value
        request.attendance_marked_at = now
        request.attendance_marked_by = actor
        request.save(
            update_fields=["attendance_status", "attendance_marked_at", "attendance_marked_by"]
        )
        for parent in parents:
            _pending_notification(
                Notification.Type.CLINIC_ATTENDANCE,
                f"클리닉 {value} 안내",
                request,
                parent=parent,
            )
        if value == ClinicRequest.AttendanceStatus.ABSENT:
            student.noshow_count = F("noshow_count") + 1
            student.save(update_fields=["noshow_count"])
            student.refresh_from_db(fields=["noshow_count"])
            if student.noshow_count >= NOSHOW_BAN_THRESHOLD and not student.clinic_banned:
                student.clinic_banned = True
                student.save(update_fields=["clinic_banned"])
            _pending_notification(
                Notification.Type.NOSHOW_WARNING, "클리닉 노쇼 경고", request, student=student
            )
            for parent in parents:
                _pending_notification(
                    Notification.Type.NOSHOW_WARNING, "클리닉 노쇼 경고", request, parent=parent
                )
    return request, student


def _pending_notification(type_, title, request, student=None, parent=None):
    """알림을 건다 — 행은 지금, 발송은 커밋 뒤(모듈 docstring). 대상 3분기 준수."""
    queue_notification(
        student=student,
        parent=parent,
        channel=Notification.Channel.KAKAO,
        type=type_,
        title=title,
        ref_type="clinic",
        ref_id=request.clinic_id,
    )


def unban(student):
    """노쇼 영구제한 해제(④ — **대표 전용**, 뷰의 IsOwner 가 강제)."""
    if not student.clinic_banned:
        raise ClinicError("클리닉 제한 상태가 아닙니다.")
    student.clinic_banned = False
    student.save(update_fields=["clinic_banned"])
    return student


# --- 평가(3표) ------------------------------------------------------------


def criteria_rows():
    """활성 평가 항목 — display_order 순(미지정은 뒤로)."""
    qs = ClinicEvalCriteria.objects.filter(is_active=True).order_by(
        F("display_order").asc(nulls_last=True), "criteria_id"
    )
    return [
        {
            "criteria_id": c.criteria_id,
            "item": c.item,
            "description": c.description,
            "display_order": c.display_order,
        }
        for c in qs
    ]


def record_evaluation(request, items, overall_result, actor):
    """평가 기록 — evaluation 1건(1:1 get_or_create) + 항목 upsert.

    **수기 입력은 result 에 기록한다**: ClinicEvaluationItem.result 는 NN 이고
    admin_override 는 "AI 판단에 대한 관리자 정정" 자리다(모델 계약). AI 연동
    전의 관리자 평가는 정정이 아니라 1차 판단이므로 result 가 맞는 축이며,
    AI 도입 후에도 이 API 의 의미(관리자 최종 기록)는 admin_override 로 옮기면
    된다. evaluated_at(AI 평가 시각)은 비워두고 reviewed_by/reviewed_at 으로
    관리자 기록을 남긴다.
    """
    if request.status != ClinicRequest.Status.APPROVED:
        raise ClinicError("승인배정된 건만 평가할 수 있습니다.")
    now = timezone.now()
    with transaction.atomic():
        evaluation, _ = ClinicEvaluation.objects.get_or_create(clinic=request)
        if overall_result is not None:
            evaluation.overall_result = overall_result
        evaluation.reviewed_by = actor
        evaluation.reviewed_at = now
        evaluation.save(update_fields=["overall_result", "reviewed_by", "reviewed_at"])
        for entry in items:
            ClinicEvaluationItem.objects.update_or_create(
                evaluation=evaluation,
                criteria_id=entry["criteria_id"],
                defaults={"result": entry["result"]},
            )
    return evaluation


def evaluation_payload(evaluation):
    items = evaluation.items.select_related("criteria").order_by("criteria_id")
    return {
        "eval_id": evaluation.eval_id,
        "clinic_id": evaluation.clinic_id,
        "overall_result": evaluation.overall_result,
        "reviewed_at": (
            timezone.localtime(evaluation.reviewed_at).isoformat()
            if evaluation.reviewed_at
            else None
        ),
        "items": [
            {
                "criteria_id": i.criteria_id,
                "item": i.criteria.item,
                "result": i.admin_override or i.result,
            }
            for i in items
        ],
    }

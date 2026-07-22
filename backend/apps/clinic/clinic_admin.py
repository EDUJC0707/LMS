"""클리닉 관리자 서비스 — 배정·출결·노쇼 밴·평가 (PRD 3.2.4 관리자 측).

규칙 강제 지점(booking.py 와 같은 구조 — ClinicError 재사용):
  ① 승인+배정: `대기`→`승인배정`. **재배정 허용**(`승인배정` 상태에서 담당·링크
     교체) — 수업 당일 현장 대응 불가 전제라 조교 사정 변경 시 수동 우회가
     있어야 한다(key_considerations §5). meet_url 은 수동 입력(Meet API 연동
     후순위 — 링크 재사용 금지 원칙은 입력하는 관리자가 지킨다).
  ② 출결 처리: `승인배정` + 미처리 건만. **재처리 400** — 결석 재처리를
     허용하면 noshow_count 가 이중 집계된다. 정정이 필요하면 대표가 unban
     으로 풀고 재집계하는 수동 절차(파괴적 정정 자동화 금지 — §5).
  ③ 노쇼: 결석 = noshow_count +1, **2회 도달 시 clinic_banned=true**
     (원천은 accounts.Student — ClinicRequest 모델 계약, 사본 금지).
  ④ 해제(unban): **대표 전용** — 노쇼 영구제한 해제는 key_considerations §2
     의 대표 전용 민감 기능 후보라서 범위 확정 전까지 가장 좁게(대표만) 연다
     (닫힘이 안전 기본값 — §5). noshow_count 는 유지 — 누적은 사실 기록이고,
     해제 후 재노쇼 시 즉시 재제한되는 것이 의도된 동작이다.

알림(출석/결석 → 학부모, 노쇼 경고 → 학생·학부모 — PRD 3.2.4)은
notifications 행(status `대기`)으로 **기록만** 한다 — 알림톡 채널 연동 대기
(key_considerations §4), 연동 시 발송 배치가 `대기` 행을 집어간다.
"""
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.accounts.models import ParentStudent
from apps.accounts.permissions import STAFF_ROLES
from apps.notifications.models import Notification

from .booking import ClinicError
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


def queue_rows(status_filter=None, date_filter=None):
    """신청 대기열 — 학생 노쇼·제한 상태 동봉(배정 판단 자료)."""
    qs = (
        ClinicRequest.objects.select_related("student__user", "assigned_staff", "slot")
        .order_by("requested_date", "requested_time", "clinic_id")
    )
    if status_filter:
        qs = qs.filter(status=status_filter)
    if date_filter:
        qs = qs.filter(requested_date=date_filter)
    return [queue_row(r) for r in qs]


def queue_row(request):
    student = request.student
    return {
        "clinic_id": request.clinic_id,
        "student": {
            "student_id": student.student_id,
            "name": student.user.name if student.user else None,
            "unique_id": student.unique_id,
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
        "meet_url": request.meet_url,
        "attendance_status": request.attendance_status,
    }


# --- 승인·배정 ------------------------------------------------------------

_ASSIGNABLE = (ClinicRequest.Status.PENDING, ClinicRequest.Status.APPROVED)


def assign(request, staff_user, meet_url):
    """승인+배정(①) — 담당 직원·미트 링크를 걸고 `승인배정`으로 전이."""
    if request.status not in _ASSIGNABLE:
        raise ClinicError("배정할 수 없는 상태입니다.")
    if staff_user is None or staff_user.role not in STAFF_ROLES or not staff_user.is_active:
        raise ClinicError("배정 대상은 활성 직원이어야 합니다.")
    request.status = ClinicRequest.Status.APPROVED
    request.assigned_staff = staff_user
    request.meet_url = meet_url
    request.save(update_fields=["status", "assigned_staff", "meet_url"])
    return request


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
    """알림 행 기록 — 발송은 알림톡 연동 대기(모듈 docstring). 대상 3분기 준수."""
    Notification.objects.create(
        student=student,
        parent=parent,
        channel=Notification.Channel.KAKAO,
        type=type_,
        title=title,
        ref_type="clinic",
        ref_id=request.clinic_id,
        status=Notification.Status.PENDING,
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

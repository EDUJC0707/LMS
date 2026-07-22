"""클리닉 신청 서비스 — 자격·정원·마감·노쇼 규칙 강제 (PRD 3.2.4·§4).

규칙 강제 지점(전부 API 레벨 — 프런트 숨김은 보조):
  ① 자격: ClinicEligibility(is_target) 대상자만 — 비대상·무판정 403
  ② 정원: (slot, requested_date)의 활성 신청 수(`대기`+`승인배정`) >=
     capacity → 마감 400. 집계는 clinic_requests 를 센다(잔여석 사본 금지 —
     ClinicSlot 모델 계약). 동시성은 트랜잭션 + select_for_update(슬롯 행
     잠금)로 정원 초과를 막는다.
  ③ 당일 마감: 당일 오전 8시(Asia/Seoul) 이후 그 날짜의 신청·변경·취소
     불가. 취소를 '변경'에 포함시킨 판단 근거: 8시 마감의 목적이 당일
     배정 인력 확정인데, 취소만 열어두면 마감 후 이탈로 같은 문제가 생긴다.
  ④ 노쇼 영구제한: students.clinic_banned(원천 — 사본 금지) → 신청·변경
     403. 취소는 허용(자원 반납 행위).
  ⑤ 중복: 같은 시험에 활성 신청 1건만.

취소는 노쇼로 집계하지 않는다(PRD 3.2.4) — cancelled_at 스탬프만 남기고
attendance_status·noshow_count·clinic_banned 를 건드리지 않는다.

시간 의미론: 기준 시각은 각 진입 함수의 timezone.now() 1회로 고정하고
당일·마감 판정은 Asia/Seoul 로컬(timezone.localdate/localtime) 기준
(2차 슬라이스 home 선례).
"""
import datetime

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from .models import ClinicEligibility, ClinicRequest, ClinicSlot

# 미트 링크 활성화 선행 시간 — 시작 5분 전(PRD 3.2.4). curriculum.home 과 공유.
CLINIC_LINK_LEAD = datetime.timedelta(minutes=5)
# 당일 신청·변경 마감 시각(PRD 3.2.4 — 오전 8시, Asia/Seoul).
SAME_DAY_CUTOFF = datetime.time(8, 0)
# 정원 집계 대상 상태(ClinicSlot 모델 계약 — 대기+승인배정).
ACTIVE_STATUSES = (ClinicRequest.Status.PENDING, ClinicRequest.Status.APPROVED)


class ClinicError(Exception):
    """규칙 위반 — message 와 http_status 를 뷰가 그대로 응답으로 옮긴다."""

    def __init__(self, message, http_status=400):
        super().__init__(message)
        self.message = message
        self.http_status = http_status


def model_weekday(date):
    """date → 모델 요일 축(0=일…6=토, ClinicSlot.weekday 계약)."""
    return (date.weekday() + 1) % 7


def _check_date_open(target_date, now):
    """③ 당일 마감 + 지난 날짜 차단 — 신청·변경·취소 공통."""
    today = timezone.localdate(now)
    if target_date < today:
        raise ClinicError("지난 날짜에는 신청·변경·취소할 수 없습니다.")
    if target_date == today and timezone.localtime(now).time() >= SAME_DAY_CUTOFF:
        raise ClinicError("당일 신청·변경·취소는 오전 8시까지만 가능합니다.")


def _ensure_can_book(student, exam):
    """① 자격 + ④ 노쇼 제한 — 신청·변경 공통 게이트."""
    eligibility = ClinicEligibility.objects.filter(exam=exam, student=student).first()
    if eligibility is None or not eligibility.is_target:
        raise ClinicError("클리닉 신청 대상이 아닙니다.", http_status=403)
    if student.clinic_banned:
        raise ClinicError("클리닉 신청이 제한된 계정입니다.", http_status=403)


def _check_duplicate(student, exam, exclude_pk=None):
    """⑤ 같은 시험에 활성 신청은 1건만."""
    dup = ClinicRequest.objects.filter(
        student=student, exam=exam, status__in=ACTIVE_STATUSES
    )
    if exclude_pk is not None:
        dup = dup.exclude(pk=exclude_pk)
    if dup.exists():
        raise ClinicError("이미 진행 중인 클리닉 신청이 있습니다.")


def active_count(slot, requested_date, exclude_pk=None):
    """(slot, date) 활성 신청 수 — 정원 판정의 유일한 집계."""
    qs = ClinicRequest.objects.filter(
        slot=slot, requested_date=requested_date, status__in=ACTIVE_STATUSES
    )
    if exclude_pk is not None:
        qs = qs.exclude(pk=exclude_pk)
    return qs.count()


def create_booking(student, exam, slot, requested_date):
    """신청 생성 — 규칙 ①~⑤ 전부 통과 시 `대기` 로 생성해 반환."""
    now = timezone.now()
    _ensure_can_book(student, exam)
    if model_weekday(requested_date) != slot.weekday:
        raise ClinicError("희망일이 슬롯 요일과 일치하지 않습니다.")
    _check_date_open(requested_date, now)
    _check_duplicate(student, exam)
    with transaction.atomic():
        locked = ClinicSlot.objects.select_for_update().get(pk=slot.pk)
        if active_count(locked, requested_date) >= locked.capacity:
            raise ClinicError("마감된 시간대입니다.")
        request = ClinicRequest.objects.create(
            student=student,
            exam=exam,
            slot=locked,
            requested_date=requested_date,
            requested_time=locked.start_time,
        )
    return request, now


def change_booking(request, slot, requested_date):
    """시간 변경 — 같은 규칙 재검증. 승인배정이었다면 재승인 대상으로 되돌린다.

    배정·링크 회수 근거: 시간이 바뀌면 기존 배정(조교·미트 링크)은 무효다 —
    링크 재사용 금지(key_considerations §4) + 관리자 재배정 흐름(PRD 3.2.4).
    """
    now = timezone.now()
    if request.status not in ACTIVE_STATUSES:
        raise ClinicError("변경할 수 없는 상태입니다.")
    _ensure_can_book(request.student, request.exam)
    _check_date_open(request.requested_date, now)  # 기존 날짜도 잠금(당일 이동 금지)
    if model_weekday(requested_date) != slot.weekday:
        raise ClinicError("희망일이 슬롯 요일과 일치하지 않습니다.")
    _check_date_open(requested_date, now)
    _check_duplicate(request.student, request.exam, exclude_pk=request.pk)
    with transaction.atomic():
        locked = ClinicSlot.objects.select_for_update().get(pk=slot.pk)
        if active_count(locked, requested_date, exclude_pk=request.pk) >= locked.capacity:
            raise ClinicError("마감된 시간대입니다.")
        request.slot = locked
        request.requested_date = requested_date
        request.requested_time = locked.start_time
        request.status = ClinicRequest.Status.PENDING
        request.assigned_staff = None
        request.meet_url = None
        request.updated_at = now
        request.save(
            update_fields=[
                "slot",
                "requested_date",
                "requested_time",
                "status",
                "assigned_staff",
                "meet_url",
                "updated_at",
            ]
        )
    return request, now


def cancel_booking(request):
    """취소 — cancelled_at 스탬프만. **노쇼로 집계하지 않는다**(PRD 3.2.4)."""
    now = timezone.now()
    if request.status not in ACTIVE_STATUSES:
        raise ClinicError("취소할 수 없는 상태입니다.")
    _check_date_open(request.requested_date, now)
    request.status = ClinicRequest.Status.CANCELLED
    request.cancelled_at = now
    request.save(update_fields=["status", "cancelled_at"])
    return request, now


# --- 조회 페이로드 조립 ---------------------------------------------------


def build_clinic_home(student, exam):
    """GET /api/student/clinic 응답 본문 — 자격·슬롯 잔여·내 신청 현황.

    상태 기반 노출(§4): 슬롯 목록은 **대상자이면서 제한이 없는** 학생에게만
    포함한다 — 비대상자·영구제한자에게는 신청 가능한 시간대 자체가 없다.
    """
    now = timezone.now()
    eligibility = ClinicEligibility.objects.filter(exam=exam, student=student).first()
    is_target = bool(eligibility and eligibility.is_target)
    my_requests = (
        ClinicRequest.objects.filter(student=student, exam=exam)
        .select_related("slot")
        .order_by("clinic_id")
    )
    payload = {
        "exam": {
            "exam_id": exam.exam_id,
            "name": exam.name,
            "exam_date": exam.exam_date.isoformat(),
        },
        "eligibility": {
            "is_target": is_target,
            "reason": eligibility.reason if eligibility else None,
        },
        "clinic_banned": student.clinic_banned,
        "my_requests": [request_block(r, now) for r in my_requests],
    }
    if is_target and not student.clinic_banned:
        payload["slots"] = _slot_list(now)
    return payload


def next_open_date(weekday, now):
    """슬롯 요일의 다음 신청 가능일 — 당일은 8시 전까지만, 지나면 다음 주."""
    today = timezone.localdate(now)
    candidate = today + datetime.timedelta(days=(weekday - model_weekday(today)) % 7)
    if candidate == today and timezone.localtime(now).time() >= SAME_DAY_CUTOFF:
        candidate += datetime.timedelta(days=7)
    return candidate


def _slot_list(now):
    """활성 슬롯 + 다음 신청 가능일 기준 잔여 정원(1쿼리 집계)."""
    slots = list(ClinicSlot.objects.filter(is_active=True).order_by("weekday", "start_time"))
    if not slots:
        return []
    dates = {slot.slot_id: next_open_date(slot.weekday, now) for slot in slots}
    cond = Q()
    for slot in slots:
        cond |= Q(slot=slot, requested_date=dates[slot.slot_id])
    counts = {
        row["slot_id"]: row["n"]
        for row in ClinicRequest.objects.filter(cond, status__in=ACTIVE_STATUSES)
        .values("slot_id")
        .annotate(n=Count("clinic_id"))
    }
    return [
        slot_block(slot, dates[slot.slot_id], counts.get(slot.slot_id, 0))
        for slot in slots
    ]


def slot_block(slot, requested_date, taken):
    """슬롯 요약 블록 — 목록·신청/변경 응답 공용(재조회 불필요 계약)."""
    return {
        "slot_id": slot.slot_id,
        "weekday": slot.weekday,
        "start_time": slot.start_time.strftime("%H:%M"),
        "end_time": slot.end_time.strftime("%H:%M"),
        "capacity": slot.capacity,
        "next_date": requested_date.isoformat(),
        "remaining": max(slot.capacity - taken, 0),
        "is_full": taken >= slot.capacity,
    }


def request_block(request, now):
    """신청 요약 블록 — 링크는 시작 5분 전부터만 노출(PRD 3.2.4).

    meet_url 은 link_active 일 때만 내린다 — 시각만 먼저 알려주고 URL 은
    활성화 전 미노출(2차 슬라이스 home 마감 목록과 동일 규칙).
    """
    start_at = timezone.make_aware(
        datetime.datetime.combine(request.requested_date, request.requested_time)
    )
    link_active = (
        request.status == ClinicRequest.Status.APPROVED
        and now >= start_at - CLINIC_LINK_LEAD
    )
    return {
        "clinic_id": request.clinic_id,
        "exam_id": request.exam_id,
        "slot_id": request.slot_id,
        "status": request.status,
        "requested_date": request.requested_date.isoformat(),
        "requested_time": request.requested_time.strftime("%H:%M"),
        "cancelled_at": (
            timezone.localtime(request.cancelled_at).isoformat()
            if request.cancelled_at
            else None
        ),
        "link_active": link_active,
        "meet_url": request.meet_url if link_active else None,
    }

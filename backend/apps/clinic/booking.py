"""클리닉 신청 서비스 — 자격·정원·마감·노쇼 규칙 강제 (PRD 3.2.4·§4).

규칙 강제 지점(전부 API 레벨 — 프런트 숨김은 보조):
  ① 자격: ClinicEligibility(is_target) 대상자만 — 비대상·무판정 403
  ② 정원: (slot, requested_date)의 활성 신청 수(`대기`+`승인배정`) >=
     capacity → 마감 400. **capacity 는 1 고정**(ClinicSlot 모델 계약,
     2026-07-21 회의)이라 활성 신청이 한 건만 있어도 그 날짜·시간은 마감이다.
     집계는 clinic_requests 를 센다(잔여석 사본 금지 — ClinicSlot 모델 계약).
     동시성은 트랜잭션 + select_for_update(슬롯 행 잠금)로 막는다 — 정원이
     1 이라 경합 창이 그만큼 좁고 결과는 더 치명적이다.
  ③ 전날 마감: 클리닉 날짜의 **전날까지만** 신청·변경·취소할 수 있다 —
     오늘(Asia/Seoul)과 지난 날짜는 시각과 무관하게 불가(2026-07-29 확정,
     구 "당일 오전 8시까지" 규칙은 폐기). 취소를 '변경'에 포함시킨 판단
     근거: 마감의 목적이 당일 배정 인력 확정인데, 취소만 열어두면 마감 후
     이탈로 같은 문제가 생긴다.
  ④ 노쇼 영구제한: students.clinic_banned(원천 — 사본 금지) → 신청·변경
     403. 취소는 허용(자원 반납 행위).
  ⑤ 중복: 같은 시험에 활성 신청 1건만.

취소는 노쇼로 집계하지 않는다(PRD 3.2.4) — cancelled_at 스탬프만 남기고
attendance_status·noshow_count·clinic_banned 를 건드리지 않는다.

시간 의미론: 기준 시각은 각 진입 함수의 timezone.now() 1회로 고정하고
마감 판정은 Asia/Seoul 로컬 날짜(timezone.localdate) 기준
(2차 슬라이스 home 선례).
"""
import datetime

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from .models import ClinicEligibility, ClinicRequest, ClinicSlot

# 미트 링크 활성화 선행 시간 — 시작 5분 전(PRD 3.2.4). curriculum.home 과 공유.
CLINIC_LINK_LEAD = datetime.timedelta(minutes=5)
# 정원 집계 대상 상태(ClinicSlot 모델 계약 — 대기+승인배정).
ACTIVE_STATUSES = (ClinicRequest.Status.PENDING, ClinicRequest.Status.APPROVED)

# 예약 가능 기간(GET .../availability) — 기본 14일, 최대 31일.
#   기본 14일: 클리닉 자격은 시험 회차 단위로 열리고 회차 주기가 주 단위라
#     2주면 다음 회차 판정 전까지를 덮고, 요일 기반 슬롯이 모든 요일 2회씩
#     노출되어 달력 한 화면이 비어 보이지 않는다.
#   최대 31일: 달력 UI 가 한 번에 그리는 최대 단위(한 달)이자 운영 상한 —
#     그보다 먼 미래는 조교 배정 계획이 서지 않아 열어도 지킬 수 없는 약속이
#     된다(무한정 미래 개방 금지). 초과 요청은 400.
AVAILABILITY_DEFAULT_DAYS = 14
AVAILABILITY_MAX_DAYS = 31

# 예약 불가 사유(응답 reason) — 마감은 숨기지 않고 사유와 함께 내린다.
REASON_FULL = "마감"
REASON_MINE = "내신청"


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
    """③ 전날 마감 — 오늘·지난 날짜 차단(신청·변경·취소 공통).

    오늘은 시각을 보지 않는다 — 자정이든 밤이든 오늘 날짜면 닫혀 있다.
    """
    today = timezone.localdate(now)
    if target_date < today:
        raise ClinicError("지난 날짜에는 신청·변경·취소할 수 없습니다.")
    if target_date == today:
        raise ClinicError("오늘 클리닉은 신청·변경·취소할 수 없습니다.")


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
    _check_date_open(request.requested_date, now)  # 기존 날짜도 잠금(오늘 것은 못 옮긴다)
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
    """GET /api/student/clinic 응답 본문 — 자격·내 신청 현황.

    **슬롯 목록은 여기 없다**: "요일 슬롯 + 슬롯별 next_date" 축으로는 달력에서
    날짜를 고르는 흐름을 그릴 수 없어 폐기하고, 날짜 축 응답인
    `availability()`(GET /api/student/clinic/availability)로 전부 옮겼다.
    이 API 는 자격 판정과 내 신청 현황(상태·링크)만 담당한다.
    """
    now = timezone.now()
    eligibility = ClinicEligibility.objects.filter(exam=exam, student=student).first()
    my_requests = (
        ClinicRequest.objects.filter(student=student, exam=exam)
        .select_related("slot")
        .order_by("clinic_id")
    )
    return {
        "exam": {
            "exam_id": exam.exam_id,
            "name": exam.name,
            "exam_date": exam.exam_date.isoformat(),
        },
        "eligibility": {
            "is_target": bool(eligibility and eligibility.is_target),
            "reason": eligibility.reason if eligibility else None,
        },
        "clinic_banned": student.clinic_banned,
        "my_requests": [request_block(r, now) for r in my_requests],
    }


def availability(student, exam, date_from=None, date_to=None):
    """GET /api/student/clinic/availability 응답 본문 — 날짜별 예약 가능 시간.

    자격 게이트(§4)는 신청과 동일(`_ensure_can_book`) — 대상이 아니거나 영구
    제한이면 403 으로 **시간표 자체를 못 본다**.

    노출 판단(무엇을 빼고 무엇을 사유와 함께 보여줄지):
    - **날짜 축에서 제거**: 지난 날짜 / 오늘(전날 마감 — 시각 무관) / 그 요일에
      활성 슬롯이 없는 날. 근거 — 학생이 취할 수 있는 행동이 없고, "지났다"는
      날짜 전체에 걸리는 사유라 시간마다 반복하면 달력이 사유 문구로 덮인다.
      폐지(is_active=false) 슬롯도 같은 이유로 존재 자체를 감춘다(신청 시
      404 존재 비노출과 같은 계약).
    - **시간 축에 사유와 함께 표시**: 마감. 근거 — PRD 3.2.4 가 "정원에 도달한
      슬롯은 신청 버튼 비활성(**마감 표시**)"를 명시한다. 숨기면 학생은 그
      시간이 원래 없는 건지 찼는지 구분할 수 없다. 내 활성 신청이 차지한
      경우는 `내신청` 으로 구분해 변경 흐름의 기준점이 보이게 한다.

    쿼리: 슬롯 1 + 예약현황 집계 1 로 고정. 날짜×슬롯 루프는 메모리에서 돈다
    (N+1 금지 — 테스트가 assertNumQueries 로 상한을 고정).
    """
    now = timezone.now()
    _ensure_can_book(student, exam)
    today = timezone.localdate(now)
    date_from = date_from or today
    if date_to is None:
        date_to = date_from + datetime.timedelta(days=AVAILABILITY_DEFAULT_DAYS - 1)
    if date_to < date_from:
        raise ClinicError("조회 시작일이 종료일보다 늦습니다.")
    if (date_to - date_from).days + 1 > AVAILABILITY_MAX_DAYS:
        raise ClinicError(f"조회 구간은 최대 {AVAILABILITY_MAX_DAYS}일입니다.")
    start = max(date_from, today + datetime.timedelta(days=1))  # 오늘은 항상 뺀다
    return {
        "exam_id": exam.exam_id,
        "range": {"from": start.isoformat(), "to": date_to.isoformat()},
        "days": _day_blocks(student, start, date_to),
    }


def _day_blocks(student, start, end):
    """[start, end] 각 날짜의 시간 목록 — 활성 슬롯이 있는 날만 담는다."""
    if start > end:
        return []
    slots = list(ClinicSlot.objects.filter(is_active=True).order_by("weekday", "start_time"))
    if not slots:
        return []
    by_weekday = {}
    for slot in slots:
        by_weekday.setdefault(slot.weekday, []).append(slot)
    taken = _taken_map(student, slots, start, end)
    days = []
    date = start
    while date <= end:
        weekday = model_weekday(date)
        day_slots = by_weekday.get(weekday)
        if day_slots:
            days.append(
                {
                    "date": date.isoformat(),
                    "weekday": weekday,
                    "times": [time_block(s, taken.get((s.slot_id, date))) for s in day_slots],
                }
            )
        date += datetime.timedelta(days=1)
    return days


def _taken_map(student, slots, start, end):
    """(slot_id, date) → (활성 신청 수, 그 중 내 신청 수) — 집계 1쿼리."""
    rows = (
        ClinicRequest.objects.filter(
            slot__in=slots, requested_date__range=(start, end), status__in=ACTIVE_STATUSES
        )
        .values("slot_id", "requested_date")
        .annotate(
            n=Count("clinic_id"),
            mine=Count("clinic_id", filter=Q(student=student)),
        )
    )
    return {(r["slot_id"], r["requested_date"]): (r["n"], r["mine"]) for r in rows}


def time_block(slot, taken=None):
    """가용 시간 1칸 — 예약가능 여부와 사유(마감/내신청)."""
    count, mine = taken or (0, 0)
    is_full = count >= slot.capacity
    return {
        "slot_id": slot.slot_id,
        "start_time": slot.start_time.strftime("%H:%M"),
        "end_time": slot.end_time.strftime("%H:%M"),
        "available": not is_full,
        "reason": (REASON_MINE if mine else REASON_FULL) if is_full else None,
    }


def slot_block(slot):
    """슬롯 요약 블록 — 신청·변경 응답 공용(재조회 불필요 계약).

    정원·잔여석은 싣지 않는다: capacity 는 1 고정이라 신청이 성공한 순간
    그 날짜·시간의 잔여는 언제나 0 이고, 값이 하나뿐인 필드는 계약이 아니라
    노이즈다(ClinicSlot 모델 계약). 프런트가 "수요일 19:00~20:00" 를 그리는 데
    필요한 요일·시간만 남긴다.
    """
    return {
        "slot_id": slot.slot_id,
        "weekday": slot.weekday,
        "start_time": slot.start_time.strftime("%H:%M"),
        "end_time": slot.end_time.strftime("%H:%M"),
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

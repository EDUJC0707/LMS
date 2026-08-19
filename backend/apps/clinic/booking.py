"""클리닉 신청 서비스 — 자격·정원·마감·노쇼 규칙 강제 (PRD 3.2.4·§4).

규칙 강제 지점(전부 API 레벨 — 프런트 숨김은 보조):
  ① 자격: ClinicEligibility(is_target) 대상자만 — 비대상·무판정 403
  ② 정원: (slot, requested_date)의 활성 신청 수(`대기`+`승인배정`) >=
     capacity → 마감 400. **capacity 는 1 고정**(ClinicSlot 모델 계약,
     2026-07-21 회의)이라 활성 신청이 한 건만 있어도 그 날짜·시간은 마감이다.
     집계는 clinic_requests 를 센다(잔여석 사본 금지 — ClinicSlot 모델 계약).
     동시성은 트랜잭션 + select_for_update(슬롯 행 잠금)로 막는다 — 정원이
     1 이라 경합 창이 그만큼 좁고 결과는 더 치명적이다.
  ③ 신청 창구: 신청할 수 있는 **날짜**는 [내일, 창구 끝] 구간뿐이다.
     - 앞쪽 끝(전날 마감): 오늘(Asia/Seoul)과 지난 날짜는 시각과 무관하게
       불가(2026-07-29 확정, 구 "당일 오전 8시까지" 규칙은 폐기). 취소를
       '변경'에 포함시킨 판단 근거: 마감의 목적이 당일 배정 인력 확정인데,
       취소만 열어두면 마감 후 이탈로 같은 문제가 생긴다.
     - 뒤쪽 끝(창구 끝): 그 시험 회차의 **시험일 다음에 오는 첫 화요일**
       까지(2026-07-29 확정 — `booking_window_end`). 창구 끝은 **취소에는
       걸지 않는다**(아래 취소 항목).
  ④ 노쇼 영구제한: students.clinic_banned(원천 — 사본 금지) → 신청·변경
     403. 취소는 허용(자원 반납 행위).
  ⑤ 중복: 같은 시험에 활성 신청 1건만.

전날까지의 취소는 노쇼로 집계하지 않는다(PRD 3.2.4) — cancelled_at 스탬프만
남기고 attendance_status·noshow_count·clinic_banned 를 건드리지 않는다.
**다만 당일 취소는 노쇼다**(FLOW 3-7, 2026-08-19 대표): 자리는 이미 비워 둘 수
없는 시점이라 전날까지 무르는 것과 같이 셀 수 없다. 그래서 당일에는 취소가
막히는 것이 아니라 **열리고 노쇼로 세진다** — 막아 두면 학생은 그냥 안 오고,
결과(노쇼 1회)는 어차피 같은데 조교만 자리가 빈다는 것을 모른 채 기다린다.
**취소에는 창구 끝을 걸지 않는다**(2026-07-29): 신청·변경은 자리를 잡는
행위라 배정 계획 안에 들어와야 하지만, 취소는 이미 잡은 자리를 반납하는
행위다 — 막으면 안 올 학생의 자리가 잠긴 채 남는다(운영이 잃기만 한다).
전날 마감은 그대로 걸린다(당일 이탈 방지). 창구가 닫힌 시점에는 아직
오지 않은 신청 날짜가 남을 수 없으므로(신청 날짜 ≤ 창구 끝 ≤ 오늘) 이
판단이 실제로 갈리는 건 관리자·이관으로 들어온 창구 밖 예약뿐이다.

시간 의미론: 기준 시각은 각 진입 함수의 timezone.now() 1회로 고정하고
마감 판정은 Asia/Seoul 로컬 날짜(timezone.localdate) 기준
(2차 슬라이스 home 선례).
"""
import datetime

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from apps.accounts.models import ParentStudent

from .conferencing import ConferenceError, get_adapter
from .models import ClinicEligibility, ClinicRequest, ClinicSlot

# 미트 링크 활성화 선행 시간 — 시작 5분 전(PRD 3.2.4). curriculum.home 과 공유.
CLINIC_LINK_LEAD = datetime.timedelta(minutes=5)
# 정원 집계 대상 상태(ClinicSlot 모델 계약 — 대기+승인배정).
ACTIVE_STATUSES = (ClinicRequest.Status.PENDING, ClinicRequest.Status.APPROVED)

# 창구 길이 — 시험일 다음날부터 **다음 수업 전날**까지(수업은 주 1회, 반별 요일).
WINDOW_DAYS = 6

# 예약 불가 사유(응답 reason) — 마감은 숨기지 않고 사유와 함께 내린다.
REASON_FULL = "마감"
REASON_MINE = "내신청"

# 창구 밖 날짜 — 신청·변경 거부 문구(취소에는 쓰지 않는다).
OUT_OF_WINDOW_MESSAGE = "클리닉 신청 기간 밖의 날짜입니다."


class ClinicError(Exception):
    """규칙 위반 — message 와 http_status 를 뷰가 그대로 응답으로 옮긴다."""

    def __init__(self, message, http_status=400):
        super().__init__(message)
        self.message = message
        self.http_status = http_status


def model_weekday(date):
    """date → 모델 요일 축(0=일…6=토, ClinicSlot.weekday 계약)."""
    return (date.weekday() + 1) % 7


def booking_window_end(exam_date):
    """③ 창구 끝 — **받을 수 있는 마지막 클리닉 날짜** = 시험일 + 6일.

    2026-07-30 대표 확정: **다음 수업 전날까지**. 수업은 반별로 주 1회이므로
    (수요반·토요반…) 다음 수업은 같은 요일 7일 뒤고, 그 전날이 창구 끝이다.
    클리닉은 다음 수업 전에 끝나야 한다 — 그게 이 규칙의 전부다.

        수요일 수업 → 창구 끝 화요일
        목요일 수업 → 창구 끝 수요일

    **요일로 못 박지 않는다.** 반마다 수업 요일이 다르므로 "다음 주 화요일"
    같은 고정 요일은 특정 반에서만 맞는다. 두 번 그렇게 잡았다가 두 번 다
    어긋났다(7/29 월요일 · 7/30 화요일). 기준은 요일이 아니라 **간격**이다.

    창구 끝을 정하는 **유일한 지점** — availability·create·change 가 전부
    이 함수를 부른다.

    ## 이 함수가 정하지 않는 것 — 신청 마감

    신청 마감은 `_check_date_open` 이 정한다. **클리닉 날짜마다 그 전날이
    마감**이라 마감일은 하나로 고정되지 않고 계속 움직인다(대표 원문:
    "신청마감은 계쏙 바뀌지 / 일요일 클리닉은 토요일까지").

    ## 창구의 시작

    여기서 정하지 않는다. **권한 부여 시점**(`ClinicEligibility.is_target` 확정)
    부터이고, 그 전에는 자격 게이트가 시간표 자체를 403 으로 막는다.
    판정은 시험 당일이 될 수도, 며칠 뒤가 될 수도 있다.
    """
    return exam_date + datetime.timedelta(days=WINDOW_DAYS)


def _check_date_open(target_date, now):
    """③ 창구 앞쪽 끝 — 오늘·지난 날짜 차단(신청·변경).

    오늘은 시각을 보지 않는다 — 자정이든 밤이든 오늘 날짜면 닫혀 있다.
    취소는 이 문을 안 쓴다: 당일에도 열려 있고 대신 노쇼로 세진다
    (`cancel_booking`).
    """
    today = timezone.localdate(now)
    if target_date < today:
        raise ClinicError("지난 날짜에는 신청·변경할 수 없습니다.")
    if target_date == today:
        raise ClinicError("오늘 클리닉은 신청·변경할 수 없습니다.")


def _check_in_window(target_date, exam):
    """③ 창구 뒤쪽 끝 — 신청·변경 전용(취소는 부르지 않는다, 모듈 docstring).

    availability 에서 안 보이는 날짜라도 API 를 직접 때리면 여기서 걸린다
    (§4 상태 기반 노출 — 숨김은 보조, 강제는 API 레벨).
    """
    if target_date > booking_window_end(exam.exam_date):
        raise ClinicError(OUT_OF_WINDOW_MESSAGE)


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
    _check_in_window(requested_date, exam)
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

    배정·링크 회수 근거: 시간이 바뀌면 기존 배정(조교·화상 링크)은 무효다 —
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
    # 창구는 **옮겨 갈 날짜**에만 건다 — 기존 날짜까지 보면 창구 밖으로
    # 들어온 예약(관리자·이관)을 창구 안으로 되돌릴 길이 막힌다.
    _check_in_window(requested_date, request.exam)
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
        # 화상 스페이스도 함께 버린다 — 링크 재사용 금지(key_considerations §4).
        # 셋을 같이 비우지 않으면 ref 만 남아 "이미 스페이스가 있다"로 보여
        # 재배정이 옛 링크를 되살린다(clinic_admin.assign 의 1건=1스페이스 판정).
        request.conference_provider = None
        request.conference_ref = None
        request.conference_url = None
        request.updated_at = now
        request.save(
            update_fields=[
                "slot",
                "requested_date",
                "requested_time",
                "status",
                "assigned_staff",
                "conference_provider",
                "conference_ref",
                "conference_url",
                "updated_at",
            ]
        )
    _drop_supervision(request)
    return request, now


def cancel_booking(request):
    """취소 — cancelled_at 스탬프. **당일이면 노쇼 1회를 같이 센다**(FLOW 3-7).

    **"당일" 을 무엇으로 재나.** 마감(그 슬롯의 전날)이 지났는가로 잰다 —
    `requested_date <= 오늘`. 슬롯 시각은 보지 않는다: 마감이 날짜 단위라
    (`_check_date_open`) 취소만 시각으로 재면 같은 날 아침 9시 취소는 공짜인데
    오후 3시 취소는 노쇼가 되고, 그 경계는 조교의 배정 계획과 아무 관계가 없다.
    자리를 다시 채울 수 있었느냐가 기준이고, 그 답이 갈리는 지점이 전날 마감이다.

    지나간 날짜도 같은 자리다 — 안 온 뒤에 무르는 것이라 당일 취소보다 무르지
    않다. 조교가 이미 결석으로 찍었으면 그 건은 `승인배정` 이 아니라 출결이
    끝난 건이지만, 상태는 그대로 `승인배정` 이라 여기로 들어올 수 있다.
    이중 집계는 `mark_attendance` 가 막는다 — `취소` 는 출결 처리 대상이 아니다.
    """
    from .clinic_admin import count_noshow

    now = timezone.now()
    if request.status not in ACTIVE_STATUSES:
        raise ClinicError("취소할 수 없는 상태입니다.")
    counts_as_noshow = request.requested_date <= timezone.localdate(now)
    with transaction.atomic():
        request.status = ClinicRequest.Status.CANCELLED
        request.cancelled_at = now
        request.save(update_fields=["status", "cancelled_at"])
        if counts_as_noshow:
            student = request.student
            parents = [
                link.parent for link in ParentStudent.objects.filter(student=student)
            ]
            count_noshow(request, student, parents)
    _drop_supervision(request)
    return request, now


def _drop_supervision(request):
    """걸어 둔 감독 예약을 거둔다 — 취소·시간 변경 뒤.

    안 거두면 **아무도 없는 방에 봇이 들어가** 빈 기록을 남기고, 옮긴 경우에는
    옛 시각과 새 시각 양쪽에 들어간다. 실패해도 사용자 동작(취소·변경)은
    이미 끝났으므로 되돌리지 않는다 — 취소가 업체 장애로 실패하면 학생은
    취소되지 않은 화면을 보게 되고 그게 훨씬 나쁘다.
    """
    from .clinic_admin import supervision_key

    try:
        get_adapter().cancel_supervision(supervision_key(request))
    except ConferenceError:
        return


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
        "history": history_rows(student, now),
    }


def history_rows(student, now):
    """지난 신청 전부 — **회차를 가리지 않는다**(최신 먼저).

    화면에서 회차 선택 드롭다운을 뺐다(2026-08-11). 신청은 지금 열린 회차
    하나로만 하고 지난 것은 한 목록으로 쌓이므로, 응답이 그 회차 것만 담으면
    화면이 나머지를 보여 줄 방법이 없다.

    줄마다 회차 이름을 붙인다 — 고르는 자리가 없어졌으니 어느 회차 것인지는
    줄이 스스로 말해야 한다.
    """
    rows = (
        ClinicRequest.objects.filter(student=student)
        .select_related("exam")
        .order_by("-requested_date", "-requested_time", "-clinic_id")
    )
    return [
        {
            **request_block(r, now),
            "exam_name": r.exam.name if r.exam else None,
        }
        for r in rows
    ]


def availability(student, exam, date_from=None, date_to=None):
    """GET /api/student/clinic/availability 응답 본문 — 날짜별 예약 가능 시간.

    자격 게이트(§4)는 신청과 동일(`_ensure_can_book`) — 대상이 아니거나 영구
    제한이면 403 으로 **시간표 자체를 못 본다**.

    구간은 **창구**(모듈 docstring ③)와 같다: 내일에서 시작해
    `booking_window_end(시험일)` 에서 끝난다. 호출자가 `to` 를 더 멀리
    보내도 창구 끝으로 잘린다 — 잡을 수 없는 날짜를 달력에 세우면 화면이
    지킬 수 없는 약속을 하게 된다. 창구가 이미 지났으면 `days` 는 빈 배열이고
    `range.to` 가 `range.from` 보다 앞선다(닫힘의 표현) — **403 이 아니다**:
    자격은 그대로인데 기간이 끝난 것이라 비대상과 다른 사실이다.

    구간 상한 상수(옛 `AVAILABILITY_DEFAULT_DAYS`=14 / `AVAILABILITY_MAX_DAYS`
    =31)는 없앴다(2026-07-29). 둘 다 "끝이 없는 창구"를 임시로 잘라 두던
    값이다 — 이제 끝은 시험일이 정하고 그 길이는 최대 7일(시험 다음 첫
    화요일까지)이라 14일 기본값은 늘 창구 밖을 가리키는 거짓말이 되고,
    31일 초과 400 은 잘라내면 그만인 입력에 에러를 내는 이중 규칙이 된다.
    상한은 창구 끝 하나로 통일한다.

    노출 판단(무엇을 빼고 무엇을 사유와 함께 보여줄지):
    - **날짜 축에서 제거**: 지난 날짜 / 오늘(당일 신청 불가 — 시각 무관) /
      창구 끝 이후 / 그 요일에 활성 슬롯이 없는 날. 근거 — 학생이 취할 수
      있는 행동이 없고, "지났다"는 날짜 전체에 걸리는 사유라 시간마다
      반복하면 달력이 사유 문구로 덮인다. 폐지(is_active=false) 슬롯도 같은
      이유로 존재 자체를 감춘다(신청 시 404 존재 비노출과 같은 계약).
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
    # 역구간은 **호출자가 준 값끼리만** 본다 — 창구 끝을 채워 넣고 비교하면
    # 창구가 지난 정상 조회(from=다음 달)가 400 이 되어 버린다.
    if date_to is not None and date_to < date_from:
        raise ClinicError("조회 시작일이 종료일보다 늦습니다.")
    window_end = booking_window_end(exam.exam_date)
    start = max(date_from, today + datetime.timedelta(days=1))  # 오늘은 항상 뺀다
    end = min(date_to, window_end) if date_to is not None else window_end
    return {
        "exam_id": exam.exam_id,
        "range": {"from": start.isoformat(), "to": end.isoformat()},
        "days": _day_blocks(student, start, end),
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

    conference_url 은 link_active 일 때만 내린다 — 시각만 먼저 알려주고 URL 은
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
        "conference_url": request.conference_url if link_active else None,
    }

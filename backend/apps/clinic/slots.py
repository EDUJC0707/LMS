"""커리의 클리닉 창 → 슬롯 표 (FLOW 1-1·3-7).

**슬롯은 손으로 만들지 않는다.** 커리가 `15:00~21:00` 같은 창을 갖고, 그 창을
한 시간 단위로 쪼갠 것이 슬롯이다. 창을 고치면 이 모듈이 표를 맞춘다.

두 가지를 지킨다.

- **월~금만 연다.** 주말 클리닉은 없다.
- **고친 날 이후부터만 적용된다.** 창에서 빠진 시간은 지우지 않고
  폐지(`is_active=False`)한다 — 이미 그 시간에 잡아 둔 학생의 신청은
  그대로 살아 있어야 하고(`ClinicRequest.slot` 이 PROTECT 다), 지난 날짜의
  기록도 "그때는 이 시간이 있었다" 로 남아야 한다.
"""
import datetime

from .models import DEFAULT_SLOT_CAPACITY, ClinicSlot

# 0=일…6=토 (Django `week_day` 가 아니라 우리 값집합). 월~금.
CLINIC_WEEKDAYS = (1, 2, 3, 4, 5)

_HOUR = datetime.timedelta(hours=1)


def hourly_windows(start, end):
    """`start`~`end` 를 한 시간짜리 (시작, 끝) 목록으로 쪼갠다.

    끝에 한 시간이 안 되게 남는 자투리는 버린다 — `15:00~21:30` 이면
    `21:00~21:30` 은 슬롯이 되지 않는다. 반 시간짜리 클리닉은 없다.
    """
    if start is None or end is None or start >= end:
        return []
    base = datetime.date(2000, 1, 1)
    cursor = datetime.datetime.combine(base, start)
    limit = datetime.datetime.combine(base, end)
    windows = []
    while cursor + _HOUR <= limit:
        nxt = cursor + _HOUR
        windows.append((cursor.time(), nxt.time()))
        cursor = nxt
    return windows


def current_capacity():
    """지금 쓰는 정원 — 새 슬롯이 물려받을 값.

    정원은 클리닉 조교 수라 **전역으로 하나**인데(FLOW 3-7) 값은 슬롯 행마다
    들고 있다. 새 슬롯이 옛 기본값 1 로 서면 조교가 둘인 날 갑자기 한 자리만
    받는 시간이 섞이므로, 살아 있는 슬롯이 쓰는 값을 그대로 물려준다.
    """
    row = ClinicSlot.objects.filter(is_active=True).order_by("slot_id").first()
    return row.capacity if row else DEFAULT_SLOT_CAPACITY


def sync_course_slots(course):
    """커리의 클리닉 창에 맞춰 그 커리의 슬롯을 세우고 지운다.

    반환은 `(생긴 수, 되살린 수, 폐지한 수)`.
    창이 비어 있으면(둘 중 하나라도 NULL) 그 커리는 클리닉을 안 여는 것이므로
    가진 슬롯을 전부 폐지한다.
    """
    windows = hourly_windows(course.clinic_start_time, course.clinic_end_time)
    wanted = {(weekday, start): end for weekday in CLINIC_WEEKDAYS for start, end in windows}

    existing = {(s.weekday, s.start_time): s for s in course.clinic_slots.all()}
    capacity = current_capacity()
    created = revived = retired = 0

    for key, end in wanted.items():
        slot = existing.get(key)
        if slot is None:
            ClinicSlot.objects.create(
                course=course,
                weekday=key[0],
                start_time=key[1],
                end_time=end,
                capacity=capacity,
            )
            created += 1
        elif not slot.is_active:
            slot.is_active = True
            slot.end_time = end
            slot.save(update_fields=["is_active", "end_time"])
            revived += 1

    stale = [s.pk for key, s in existing.items() if key not in wanted and s.is_active]
    if stale:
        retired = ClinicSlot.objects.filter(pk__in=stale).update(is_active=False)

    return created, revived, retired


def parse_time(raw, label):
    """`"15:00"` → `datetime.time`. 빈 값은 None(그 커리는 클리닉을 안 연다)."""
    if raw in (None, ""):
        return None
    if not isinstance(raw, str):
        raise ValueError(f"{label} 형식이 올바르지 않습니다.")
    try:
        return datetime.datetime.strptime(raw.strip(), "%H:%M").time()
    except ValueError as exc:
        raise ValueError(f"{label}은(는) HH:MM 으로 적어 주세요.") from exc


def set_course_hours(course, start_raw, end_raw):
    """커리의 클리닉 창을 바꾸고 슬롯을 맞춘다 (FLOW 1-1·3-7).

    한쪽만 비우는 것은 막는다 — 시작만 있고 끝이 없는 창은 슬롯을 몇 개
    세워야 할지 정하지 못한다. 둘 다 비우면 클리닉을 안 여는 커리다.
    """
    start = parse_time(start_raw, "클리닉 시작")
    end = parse_time(end_raw, "클리닉 종료")
    if (start is None) != (end is None):
        raise ValueError("클리닉 시작과 종료를 함께 적어 주세요.")
    if start is not None and start >= end:
        raise ValueError("클리닉 종료는 시작보다 늦어야 합니다.")
    if start is not None and not hourly_windows(start, end):
        raise ValueError("클리닉 시간대는 한 시간 이상이어야 합니다.")
    course.clinic_start_time = start
    course.clinic_end_time = end
    course.save(update_fields=["clinic_start_time", "clinic_end_time"])
    created, revived, retired = sync_course_slots(course)
    return {
        "course_id": course.course_id,
        "clinic_start_time": start.strftime("%H:%M") if start else None,
        "clinic_end_time": end.strftime("%H:%M") if end else None,
        "slots": {"created": created, "revived": revived, "retired": retired},
    }

"""반 개설 서비스 — 커리 + 반 + 회차 (FLOW 1-2·1-3).

**커리와 반은 한 화면에서 만든다**(FLOW 1-2). 커리만 있고 반이 없으면 아무도
그 수업을 듣지 않으니 쓸 일이 없어서, 만드는 입구가 하나다.

**반을 만들면 커리 총주차만큼 회차가 채워진다**(FLOW 1-3) — 개강일에서 주
단위로. 반의 주차는 별도 표가 아니라 `grades.ClassSession` 이다(주 1회라
주차 = 회차 — FLOW 1-1). 커리 쪽 주차(`CourseWeek`)는 **내용·영상이 붙는
자리**라 반마다 갖지 않고 커리에 하나씩만 있으면 되며, 회차가 그것을 가리킨다.
없으면 여기서 만든다 — 총주차가 곧 커리의 주차 수이기 때문이다.

만든 `CourseWeek` 은 `start_date`·`release_at` 이 비어 있어 **학생에게 안
보인다**(`CourseWeekQuerySet.released()` — 닫힘이 안전 기본값,
key_considerations §5). 내용과 공개 시점은 커리 편집에서 채운다.

주차 날짜 수정·반 수정·삭제는 여기 없다 — 생성과 조회까지다.
"""
import datetime

from django.db import IntegrityError, models, transaction

from apps.grades.models import ClassSession

from .models import Class, Course, CourseEnrollment, CourseWeek

# 총주차 상한 — 1년치. 오타로 60000 이 들어오면 회차가 그만큼 생긴다.
MAX_TOTAL_WEEKS = 52


def list_courses(today=None):
    """커리로 묶은 반 목록 — 반이 하나도 없는 커리는 빠진다(FLOW 1-2).

    반마다 진행 주차(`current_week`/`week_count`)와 수강생 수를 함께 센다.
    """
    today = today or datetime.date.today()
    rows = (
        Class.objects.select_related("course")
        .annotate(
            week_count=models.Count("sessions", distinct=True),
            current_week=models.Count(
                "sessions",
                filter=models.Q(sessions__session_date__lte=today),
                distinct=True,
            ),
            student_count=models.Count(
                "enrollments",
                filter=models.Q(enrollments__status=CourseEnrollment.Status.ENROLLED),
                distinct=True,
            ),
        )
        .order_by("-course_id", "class_id")
    )
    courses = []
    by_course = {}
    for klass in rows:
        group = by_course.get(klass.course_id)
        if group is None:
            group = {
                "course_id": klass.course_id,
                "name": klass.course.name,
                "total_weeks": klass.course.total_weeks,
                "classes": [],
            }
            by_course[klass.course_id] = group
            courses.append(group)
        group["classes"].append(class_block(klass))
    return courses


def class_block(klass):
    """반 한 줄 — 목록·생성 응답 공용. 집계는 annotate 가 없으면 세어서 채운다."""
    week_count = getattr(klass, "week_count", None)
    if week_count is None:
        week_count = klass.sessions.count()
        current_week = klass.sessions.filter(
            session_date__lte=datetime.date.today()
        ).count()
        student_count = klass.enrollments.filter(
            status=CourseEnrollment.Status.ENROLLED
        ).count()
    else:
        current_week = klass.current_week
        student_count = klass.student_count
    return {
        "class_id": klass.class_id,
        "course_id": klass.course_id,
        "course_name": klass.course.name,
        "name": klass.name,
        "start_date": klass.start_date.isoformat() if klass.start_date else None,
        "week_count": week_count,
        "current_week": current_week,
        "student_count": student_count,
    }


@transaction.atomic
def open_class(*, course_id, course_name, total_weeks, name, start_date):
    """커리(있으면 재사용) + 반 + 회차를 만든다. 입력 오류는 ValueError."""
    name = (name or "").strip() if isinstance(name, str) else ""
    if not name:
        raise ValueError("수강반명을 적어 주세요.")
    start_date = _parse_date(start_date)
    course = _resolve_course(course_id, course_name, total_weeks)
    try:
        klass = Class.objects.create(course=course, name=name, start_date=start_date)
    except IntegrityError as exc:  # UQ(course, name)
        raise ValueError(f"이 커리에 같은 이름의 반이 있습니다: {name}") from exc
    _fill_sessions(klass, course.total_weeks, start_date)
    return klass


def _resolve_course(course_id, course_name, total_weeks):
    if course_id is not None:
        course = Course.objects.filter(pk=_as_int(course_id, "커리")).first()
        if course is None:
            raise ValueError("커리를 찾을 수 없습니다.")
        return course
    course_name = (course_name or "").strip() if isinstance(course_name, str) else ""
    if not course_name:
        raise ValueError("커리명을 적어 주세요.")
    weeks = _as_int(total_weeks, "총주차")
    if not 1 <= weeks <= MAX_TOTAL_WEEKS:
        raise ValueError(f"총주차는 1 이상 {MAX_TOTAL_WEEKS} 이하여야 합니다.")
    return Course.objects.create(name=course_name, total_weeks=weeks)


def _fill_sessions(klass, total_weeks, start_date):
    """개강일에서 주 단위로 총주차만큼 — 1주차 9/4 · 2주차 9/11 · … (FLOW 1-3)."""
    for week_no in range(1, total_weeks + 1):
        week, _ = CourseWeek.objects.get_or_create(course=klass.course, week_no=week_no)
        ClassSession.objects.create(
            klass=klass,
            week_no=week_no,
            session_date=start_date + datetime.timedelta(weeks=week_no - 1),
            course_week=week,
        )


def _parse_date(value):
    try:
        return datetime.date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("개강일 형식은 YYYY-MM-DD 입니다.") from exc


def _as_int(value, label):
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} 값이 올바르지 않습니다.") from exc

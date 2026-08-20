"""반 개설 서비스 — 커리 + 반 + 회차 (FLOW 1-2·1-3).

**커리와 반은 한 화면에서 만든다**(FLOW 1-2). 커리만 있고 반이 없으면 아무도
그 수업을 듣지 않으니 쓸 일이 없어서, 만드는 입구가 하나다.

**반을 만들면 커리 총주차만큼 회차가 채워진다**(FLOW 1-3) — 개강일에서 주
단위로. 반의 주차는 별도 표가 아니라 `grades.ClassSession` 이다(주 1회라
주차 = 회차 — FLOW 1-1). 커리 쪽 주차(`CourseWeek`)는 **내용·영상이 붙는
자리**라 반마다 갖지 않고 커리에 하나씩만 있으면 되며, 회차가 그것을 가리킨다.
없으면 여기서 만든다 — 총주차가 곧 커리의 주차 수이기 때문이다.

만든 `CourseWeek` 에는 **공개 시점만 찍는다** — 날짜는 반의 것이라
(`ClassSession.session_date`) 커리 주차에 담지 않는다. 비워 두면 학생·학부모
홈이 `released()` 로 전 주차를 걸러 내 반을 연 첫날 화면이 텅 비므로 공개
시점은 반을 연 시각으로 찍는다. 내용(제목·학습계획)은 커리 편집에서 채운다.

**과목은 없으면 만든다**(FLOW 1-2 — 과목은 신규 입력이 되는 드롭다운).
반대로 **구분은 값집합 밖을 거절한다** — 열어 두면 표기가 흔들려 아래 층
분류가 지저분해진다.

**주차 날짜 수정과 반별 주차 추가·삭제도 여기 있다**(FLOW 1-3). 앞 주차를
고치면 뒤가 같은 폭으로 따라 밀리고(휴강이 그 모양이다), 주차를 더하고 지우는
것은 반에서만 하므로 커리 총주차는 안 바뀐다. **번호는 안 움직인다.**
"""
import datetime

from django.db import IntegrityError, models, transaction
from django.utils import timezone

from apps.accounts.models import Student
from apps.grades.models import ClassSession

from .models import Class, Course, CourseEnrollment, CourseWeek, Subject

# 총주차 상한 — 1년치. 오타로 60000 이 들어오면 회차가 그만큼 생긴다.
MAX_TOTAL_WEEKS = 52


def list_courses(today=None):
    """커리로 묶은 반 목록 — 반이 하나도 없는 커리는 빠진다(FLOW 1-2).

    반마다 진행 주차(`current_week`/`week_count`)와 수강생 수를 함께 센다.
    """
    today = today or datetime.date.today()
    rows = (
        Class.objects.select_related("course__subject")
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
                "subject": klass.course.subject.name if klass.course.subject else None,
                "total_weeks": klass.course.total_weeks,
                "classes": [],
            }
            by_course[klass.course_id] = group
            courses.append(group)
        group["classes"].append(class_block(klass))
    return courses


def list_subjects():
    """구분↔과목 — 새 커리를 만들 때 고르는 값 (FLOW 1-2).

    커리가 하나도 없는 과목도 골라야 해서 `list_courses` 와 따로 센다.
    """
    return list(Subject.objects.order_by("track", "name").values("track", "name"))


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
def open_class(*, course_id, course_name, total_weeks, track, subject, name, start_date):
    """커리(있으면 재사용) + 반 + 회차를 만든다. 입력 오류는 ValueError."""
    name = (name or "").strip() if isinstance(name, str) else ""
    if not name:
        raise ValueError("수강반명을 적어 주세요.")
    start_date = _parse_date(start_date)
    course = _resolve_course(course_id, course_name, total_weeks, track, subject)
    try:
        klass = Class.objects.create(course=course, name=name, start_date=start_date)
    except IntegrityError as exc:  # UQ(course, name)
        raise ValueError(f"이 커리에 같은 이름의 반이 있습니다: {name}") from exc
    _fill_sessions(klass, course.total_weeks, start_date)
    return klass


def _resolve_course(course_id, course_name, total_weeks, track, subject):
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
    return Course.objects.create(
        name=course_name, total_weeks=weeks, subject=_resolve_subject(track, subject)
    )


def _resolve_subject(track, name):
    """구분은 골라야만 하고, 과목은 없으면 만든다 (FLOW 1-2).

    구분에 새 값을 넣지 못하게 막는 자리가 여기다 — 값집합 밖은 거절한다.
    """
    if track not in Subject.Track.values:
        raise ValueError("과목구분을 골라 주세요.")
    name = (name or "").strip() if isinstance(name, str) else ""
    if not name:
        raise ValueError("과목을 적어 주세요.")
    subject, _ = Subject.objects.get_or_create(track=track, name=name)
    return subject


def _fill_sessions(klass, total_weeks, start_date):
    """개강일에서 주 단위로 총주차만큼 — 1주차 9/4 · 2주차 9/11 · … (FLOW 1-3).

    날짜는 회차에만 담는다. 커리 주차는 반이 여럿이라 어느 반의 날짜를 담을지가
    애초에 모호하고, 소비자 화면도 이제 `ClassSession.session_date` 를 본다.
    """
    for week_no in range(1, total_weeks + 1):
        week_start = start_date + datetime.timedelta(weeks=week_no - 1)
        week = _course_week(klass.course, week_no)
        ClassSession.objects.create(
            klass=klass,
            week_no=week_no,
            session_date=week_start,
            course_week=week,
            exam=_week_exam(week),
        )


def _week_exam(week):
    """그 커리 주차가 정한 시험 — 회차는 그것을 가리킬 뿐이다(FLOW 3-3).

    시험은 커리를 만들 때 미리 채워 두므로, 나중에 열린 반의 회차도 그 자리에서
    같은 시험을 물고 시작한다. 조교가 반마다 다시 고르지 않는다.
    """
    return getattr(week, "exam", None)


def _course_week(course, week_no):
    """회차가 물릴 커리 주차 — 없으면 만든다. 내용은 커리 편집에서 채운다.

    공개 시점을 지금으로 찍는다. 비워 두면 `released()` 가 전 주차를 걸러 내
    반을 연 첫날 학생·학부모 화면이 텅 빈다. 날짜는 아무것도 발동시키지
    않으므로(FLOW 1-4) 공개 시점은 개강일이 아니라 반을 연 시각이다.
    """
    now = timezone.now()
    week, created = CourseWeek.objects.get_or_create(
        course=course, week_no=week_no, defaults={"release_at": now}
    )
    if not created and week.release_at is None and week.start_date is None:
        # 공개 근거 없이 만들어진 주차 — 잠긴 채로 남지 않게 찍는다
        CourseWeek.objects.filter(pk=week.pk).update(release_at=now)
    return week


# --- 반의 주차 — 날짜 수정 · 추가 · 삭제 (FLOW 1-3) -----------------------


def list_sessions(klass):
    """반의 주차 목록 — 번호와 날짜. 번호 순."""
    return [
        {"week_no": s.week_no, "session_date": s.session_date.isoformat()}
        for s in klass.sessions.order_by("week_no")
    ]


def class_detail(klass):
    """반 하나 — 주차와 명단. 주차 편집·반 이동 화면이 같이 쓴다."""
    students = (
        Student.objects.filter(
            course_enrollments__klass=klass,
            course_enrollments__status=CourseEnrollment.Status.ENROLLED,
        )
        .select_related("user")
        .order_by("student_id")
    )
    return {
        "class": class_block(klass),
        "sessions": list_sessions(klass),
        "students": [
            {
                "student_id": s.student_id,
                "name": s.user.name if s.user else None,
                "login_id": s.user.login_id if s.user else None,
            }
            for s in students
        ],
    }


@transaction.atomic
def move_week(klass, week_no, session_date):
    """주차 날짜를 고친다 — **뒤 주차가 같은 폭으로 따라 밀린다**(FLOW 1-3).

    휴강이 그 모양이라 별도의 밀기 버튼이 없다. 움직이는 것은 날짜뿐이고
    번호는 그대로다 — 출결·성적·영상 권한이 번호로 붙어 있다.
    """
    session = klass.sessions.filter(week_no=week_no).first()
    if session is None:
        raise ValueError("주차를 찾을 수 없습니다.")
    delta = _parse_date(session_date) - session.session_date
    if delta:
        following = list(klass.sessions.filter(week_no__gte=week_no))
        for row in following:
            row.session_date += delta
        ClassSession.objects.bulk_update(following, ["session_date"])
    return list_sessions(klass)


@transaction.atomic
def add_week(klass):
    """반에 주차를 하나 더한다 — 마지막 다음 번호, 마지막 + 일주일 (FLOW 1-3).

    커리 총주차는 안 바뀐다. 커리 주차가 없는 번호면 여기서 만든다.
    """
    last = klass.sessions.order_by("-week_no").first()
    if last is not None and last.week_no is not None:
        week_no = last.week_no + 1
        session_date = last.session_date + datetime.timedelta(weeks=1)
    elif klass.start_date is not None:
        week_no, session_date = 1, klass.start_date
    else:
        raise ValueError("개강일이 없는 반입니다.")
    week = _course_week(klass.course, week_no)
    ClassSession.objects.create(
        klass=klass,
        week_no=week_no,
        session_date=session_date,
        course_week=week,
        exam=_week_exam(week),
    )
    return list_sessions(klass)


@transaction.atomic
def remove_week(klass, week_no):
    """반의 마지막 주차를 지운다 (FLOW 1-3).

    **마지막만 지운다.** 가운데를 지우면 번호에 구멍이 나고, 그 구멍을 메우려면
    번호를 다시 매겨야 하는데 그것은 FLOW 1-3 이 기각한 것이다. 한 주 쉬는 것은
    삭제가 아니라 날짜를 미는 일이다(`move_week`).

    **기록이 붙은 주차는 거절한다.** 회차가 지워지면 출결과 과제가 CASCADE 로
    같이 사라지고, 워크북·청구는 회차를 가리키던 끈이 끊긴다 — 조교의 실수 한
    번으로 되돌릴 수 없는 소실이 난다(key_considerations §5 — 파괴적 작업).
    커리 주차(`CourseWeek`)는 다른 반도 쓰므로 남긴다.

    **시험은 막지 않는다**(2026-08-20). 시험은 커리 주차의 것이고 회차는 그것을
    가리킬 뿐이라(FLOW 3-3) 회차를 지워도 문항·정답·성적은 그대로 남고, 주차를
    다시 더하면 그 자리에서 다시 붙는다. 옛 세계에서는 회차가 시험을 담고 있어
    지우면 사라졌다.
    """
    last = klass.sessions.order_by("-week_no").first()
    if last is None or last.week_no != week_no:
        raise ValueError("마지막 주차만 지울 수 있습니다.")
    if _has_records(last):
        raise ValueError("기록이 있는 주차는 지울 수 없습니다.")
    last.delete()
    return list_sessions(klass)


def _has_records(session):
    """출결·과제·워크북·청구가 걸린 회차인가."""
    return (
        session.attendances.exists()
        or session.assignments.exists()
        or session.workbook_submissions.exists()
        or session.triggered_orders.exists()
    )


# --- 반 이동 (FLOW 3-9) ---------------------------------------------------


@transaction.atomic
def move_student(klass, student_id):
    """학생을 이 반으로 옮긴다 — **옮기는 즉시 그 반의 룰**(FLOW 3-9).

    수강(`CourseEnrollment.klass`)만 갈아 끼운다. 옮기면 출결표 명단이 수강에서
    나오므로 새 반에 뜨고 옛 반에서 빠지는 것이 같은 한 줄로 끝난다.

    **지난 기록은 옛 반에 남는다.** 출결·성적은 그 반의 회차(`ClassSession`)에
    달려 있고 회차는 안 움직인다 — "옮기는 즉시" 라는 말이 지난 수업까지
    소급한다는 뜻은 아니다. 옛 반 출결표가 그 학생 줄을 잃지 않도록 명단은
    **그 회차에 기록이 있는 학생도 포함**한다(grades.attendance_admin).

    이미 나간 영상·잡힌 클리닉은 건드리지 않는다 — 회수는 지급 시점 기준이고
    클리닉은 슬롯에 붙어 있어 반과 무관하다.
    """
    enrollment = (
        CourseEnrollment.objects.filter(
            student_id=student_id,
            course=klass.course,
            status=CourseEnrollment.Status.ENROLLED,
        )
        .order_by("enrollment_id")
        .first()
    )
    if enrollment is None:
        raise ValueError("이 커리를 듣는 학생이 아닙니다.")
    if enrollment.klass_id == klass.pk:
        return class_detail(klass)
    enrollment.klass = klass
    try:
        enrollment.save(update_fields=["klass"])
    except IntegrityError as exc:  # UQ(student, klass)
        raise ValueError("이미 그 반에 있는 학생입니다.") from exc
    return class_detail(klass)


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

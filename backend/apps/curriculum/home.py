"""캘린더 홈 페이로드 조립 서비스 — 학생 홈·학부모 홈 공용 (PRD 3.2.0·3.4·§4).

학생 홈(/api/student/home)과 학부모 홈(/api/parent/home)이 같은 함수
`build_home_payload()` 를 쓴다 — 캘린더·마감 로직의 이중 구현 금지(PRD 3.2.0
"학생·학부모 동일 화면"). 학부모 전용 블록(payment_status·absences)만
include_billing 플래그로 추가된다.

상태 기반 노출(PRD §4) 강제 지점:
- 미등록(예비등록)·퇴원: bare 페이로드 — 캘린더·마감 없이 구매 가능 교재만
  (닫힘이 안전 기본값, key_considerations §5).
- 주차: `CourseWeek.objects.released()` 만 내용을 내린다(유일 진입 계약).
  미공개 주차는 `{week_no, locked: true}` 스텁 — 제목·날짜·계획 전부 미노출.
- 복습영상: `VideoGrant.objects.active()` 만(만료·회수 즉시 소멸).
- 마감 목록: 자격 없는 유형은 항목 자체가 없다(빈 리스트 허용).

시간 의미론: 기준 시각은 이 모듈의 timezone.now() 1회 호출로 고정하고,
오늘·D-n 은 Asia/Seoul 로컬 날짜(timezone.localdate) 기준으로 계산한다.
"""
import calendar as pycalendar
import datetime

from django.db.models import Prefetch
from django.utils import timezone

from apps.accounts.models import Student

# 미트 링크 활성화 선행 시간(시작 5분 전, PRD 3.2.4) — 클리닉 신청 서비스와
# 공유하는 단일 상수. 원천은 clinic.booking(4차 슬라이스 추출).
from apps.clinic.booking import CLINIC_LINK_LEAD
from apps.clinic.models import ClinicRequest
from apps.grades.models import Attendance, ClassSession
from apps.payments.models import Order, Product
from apps.videos.models import MakeupGrant, VideoGrant

from .models import CourseEnrollment, WeekDayPlan


def build_home_payload(student, month=None, include_billing=False):
    """캘린더 홈 응답 본문을 조립한다.

    - student: 대상 학생(호출측이 user 를 select_related 로 로드해 둘 것 —
      쿼리 수 계약 유지).
    - month: (year, month) 또는 None(기본 = Asia/Seoul 현재 월).
    - include_billing: 학부모 홈 전용 블록(payment_status·absences) 포함 여부.
      학부모 홈은 읽기 전용 조회라 추가 검증 없이 블록만 늘어난다(PRD 3.4).
    """
    now = timezone.now()
    today = timezone.localdate(now)
    year, month_no = month if month is not None else (today.year, today.month)

    # --- 미등록·퇴원: bare (PRD §4 "첫 로그인 거의 bare") -----------------
    if student.enrollment_status != Student.EnrollmentStatus.REGISTERED:
        payload = {
            "student": _student_block(student),
            "purchasable_products": _purchasable_products(),
        }
        if include_billing:
            # 학부모는 미등록 자녀도 결제 상태는 본다(교재 결제가 유일 개방 액션)
            payload["payment_status"] = _payment_status(_orders(student))
        return payload

    first = datetime.date(year, month_no, 1)
    last = datetime.date(year, month_no, pycalendar.monthrange(year, month_no)[1])

    enrollments = list(
        CourseEnrollment.objects.filter(
            student=student, status=CourseEnrollment.Status.ENROLLED
        )
        .select_related("course")
        .order_by("enrollment_id")
    )
    course_ids = [e.course_id for e in enrollments]
    # 캘린더 커리큘럼 축은 첫 활성 수강 1건 기준(현 운영: 학생당 강좌 1개).
    primary = enrollments[0] if enrollments else None

    attendances = list(
        Attendance.objects.filter(
            student=student, session__session_date__range=(first, last)
        )
        .select_related("session")
        .order_by("session__session_date")
    )
    session_dates = set(
        ClassSession.objects.filter(
            session_date__range=(first, last), course_week__course_id__in=course_ids
        ).values_list("session_date", flat=True)
    )
    orders = _orders(student)

    # 주차 데이터는 1회 로드해 진행 표기(_course_block)와 주차 목록(_weeks)이
    # 공유한다 — released() 이중 실행 방지(쿼리 수 계약).
    week_nos, released_weeks = _load_weeks(primary, now) if primary else ([], [])

    payload = {
        "student": _student_block(student),
        "month": f"{year:04d}-{month_no:02d}",
        "today": today.isoformat(),
        "course": (
            _course_block(primary, enrollments, today, week_nos, released_weeks)
            if primary
            else None
        ),
        "calendar": {
            "days": _days(attendances, session_dates),
            "weeks": _weeks(primary.course, week_nos, released_weeks) if primary else [],
        },
        "deadlines": _deadlines(student, orders, today, now),
    }
    if include_billing:
        payload["payment_status"] = _payment_status(orders)
        payload["absences"] = _absences(attendances)
    return payload


# --- 블록별 조립 ---------------------------------------------------------


def _student_block(student):
    """이름·반·등록상태 최소 노출(개인정보 최소 원칙 — 원번·연락처 미포함)."""
    return {
        "student_id": student.student_id,
        "name": student.user.name if student.user else None,
        "current_class": student.current_class,
        "enrollment_status": student.enrollment_status,
    }


def _purchasable_products():
    """구매 가능(판매 중) 교재 목록 — bare 화면의 유일한 콘텐츠."""
    return [
        {"product_id": p.product_id, "name": p.name, "price": p.price}
        for p in Product.objects.filter(is_active=True).order_by("product_id")
    ]


def _orders(student):
    """학생의 주문 전체 1회 조회 — 마감(미결제)·결제 상태 블록이 공유한다."""
    return list(
        Order.objects.filter(student=student).select_related("product").order_by("order_id")
    )


def _load_weeks(primary, now):
    """주차 축 1회 로드 — (전체 week_no 목록, 공개 주차 목록[학습계획 prefetch]).

    공개 판정은 `CourseWeek.objects.released()` 가 유일 계약(PRD §4).
    """
    course = primary.course
    week_nos = list(course.weeks.order_by("week_no").values_list("week_no", flat=True))
    released_weeks = list(
        course.weeks.released(at=now).prefetch_related(
            Prefetch(
                "day_plans", queryset=WeekDayPlan.objects.order_by("display_order", "day_no")
            )
        )
    )
    return week_nos, released_weeks


def _course_block(primary, enrollments, today, week_nos, released_weeks):
    """진행 표기(현재 주차/전체 주차)·반·수업 요일."""
    course = primary.course
    current_week = max(
        (
            w.week_no
            for w in released_weeks
            if w.start_date is not None and w.start_date <= today
        ),
        default=None,
    )
    return {
        "course_id": course.course_id,
        "name": course.name,
        "class_name": primary.class_name,
        "total_weeks": len(week_nos),
        "current_week": current_week,
        "class_weekdays": sorted(
            {e.primary_weekday for e in enrollments if e.primary_weekday is not None}
        ),
    }


def _days(attendances, session_dates):
    """날짜별 출결 도장·예정 수업 — 뭔가 있는 날만 담는 희소 리스트."""
    stamps = {a.session.session_date: a.status for a in attendances}
    return [
        {
            "date": d.isoformat(),
            "attendance": stamps.get(d),
            "has_class_session": d in session_dates,
        }
        for d in sorted(set(stamps) | session_dates)
    ]


def _weeks(course, week_nos, released_weeks):
    """주차 목록 — released() 만 내용 노출, 미공개는 잠김 스텁(PRD §4).

    잠김 스텁은 `{week_no, locked}` 두 키뿐이다 — 제목·날짜·공지·계획을
    내리면 미래 커리큘럼이 유출된다(경쟁사 정찰 방지 목적 자체가 무너짐).
    """
    released_by_no = {w.week_no: w for w in released_weeks}
    weeks = []
    for no in week_nos:
        week = released_by_no.get(no)
        if week is None:
            weeks.append({"week_no": no, "locked": True})
            continue
        weeks.append(
            {
                "week_no": no,
                "locked": False,
                "label": f"{course.name} {no}주차",
                "title": week.title,
                "start_date": week.start_date.isoformat() if week.start_date else None,
                "end_date": week.end_date.isoformat() if week.end_date else None,
                "offline_notice": week.offline_notice,
                "day_plans": [
                    {"day_no": p.day_no, "title": p.title, "content": p.content}
                    for p in week.day_plans.all()
                ],
            }
        )
    return weeks


def _deadlines(student, orders, today, now):
    """마감 임박 목록 — 임박 순 정렬, 자격 없는 유형은 항목 자체 미포함.

    ① 클리닉: 승인배정 + 오늘 이후. 미트 링크는 시작 5분 전 규칙(PRD 3.2.4)
       이라 URL 은 내리지 않고 시각·활성화 여부만 내린다.
    ② 영상만료: 활성 권한(active())의 만료 D-n — 만료 순.
    ③ 교재결제: 미결제 주문. 결제 기한 컬럼은 스키마에 없어 due 없음으로
       내리고 정렬 최후순위에 둔다(기한 정책 확정 시 값만 채우면 됨).

    D-n 은 Asia/Seoul 로컬 날짜 차이(오늘=0). 정렬 키: due 없는 항목 뒤로,
    같은 날짜면 유형 나열 순서(①→②→③) 유지(stable sort).
    """
    items = []
    clinic_requests = ClinicRequest.objects.filter(
        student=student,
        status=ClinicRequest.Status.APPROVED,
        requested_date__gte=today,
    ).order_by("requested_date", "requested_time")
    for req in clinic_requests:
        start_at = timezone.make_aware(
            datetime.datetime.combine(req.requested_date, req.requested_time)
        )
        items.append(
            {
                "kind": "클리닉",
                "due_date": req.requested_date.isoformat(),
                "d_day": (req.requested_date - today).days,
                "clinic_id": req.clinic_id,
                "date": req.requested_date.isoformat(),
                "start_time": req.requested_time.strftime("%H:%M"),
                "link_active": now >= start_at - CLINIC_LINK_LEAD,
            }
        )

    grants = (
        VideoGrant.objects.active(at=now)
        .filter(student=student)
        .select_related("course_week__course")
        .order_by("expires_at")
    )
    for grant in grants:
        due = timezone.localdate(grant.expires_at)
        items.append(
            {
                "kind": "영상만료",
                "due_date": due.isoformat(),
                "d_day": (due - today).days,
                "grant_id": grant.grant_id,
                "course_name": grant.course_week.course.name,
                "week_no": grant.course_week.week_no,
                "expires_at": timezone.localtime(grant.expires_at).isoformat(),
            }
        )

    for order in orders:
        if order.status != Order.Status.UNPAID:
            continue
        items.append(
            {
                "kind": "교재결제",
                "due_date": None,
                "d_day": None,
                "order_id": order.order_id,
                "product_name": order.product.name,
                "amount": order.amount,
            }
        )

    items.sort(key=lambda item: (item["due_date"] is None, item["due_date"] or ""))
    return items


def _payment_status(orders):
    """자녀 교재 청구·결제 상태(학부모 홈, PRD 3.2.0·3.4 — 읽기 전용)."""
    return [
        {
            "order_id": o.order_id,
            "product_name": o.product.name,
            "amount": o.amount,
            "status": o.status,
            "is_billed": o.is_billed,
            "billed_at": timezone.localtime(o.billed_at).isoformat() if o.billed_at else None,
            "paid_at": timezone.localtime(o.paid_at).isoformat() if o.paid_at else None,
        }
        for o in orders
    ]


def _absences(attendances):
    """월 내 결석일 + 동보 신청 여부(학부모 홈, PRD 3.2.0 학부모 관점).

    출결 SSOT(attendances)에서 파생하며 동보 상태는 makeup_grants 를 참조만
    한다(사본 금지 — key_considerations §6). makeup_status None = 미신청.
    """
    absent = [a for a in attendances if a.status == Attendance.Status.ABSENT]
    makeup_by_attendance = {}
    if absent:
        makeup_rows = MakeupGrant.objects.filter(
            attendance_id__in=[a.id for a in absent]
        ).order_by("makeup_id")
        makeup_by_attendance = {m.attendance_id: m.status for m in makeup_rows}
    return [
        {
            "date": a.session.session_date.isoformat(),
            "makeup_status": makeup_by_attendance.get(a.id),
        }
        for a in absent
    ]

"""학생 명부 조회 서비스 — 직원 공통 조회 (2026-07-28 갭 보강, PRD 3.1.5·3.1.7).

직원 화면 여럿이 "학생을 고르는" 동작을 공유한다 — 워크북 사진 업로드 대상
지정(3.1.7, 조교), 예비등록→등록 전환 대상 찾기(3.1.5, 계정관리), 동보·상담
대상 확인. 그 공통 조회를 여기 하나로 둔다(뷰는 게이트·입력 검증만 —
staff_admin·attendance_admin 선례).

## 권한 판단 — `IsStaffRole`(직원 공통), 기능 키 게이트 아님

소비자가 둘 이상이라 **기능 키 하나로 묶으면 한쪽이 막힌다**: `워크북업로드`로
걸면 계정관리자가, `계정관리`로 걸면 조교가 후보 0명이 된다. 남은 선택지는
복수 기능 키 OR 과 역할 게이트인데 후자를 택했다:

1. 복수 키 OR 은 소비자가 늘 때마다 이 목록을 고쳐야 한다 — 기능 키는
   "화면 열기"의 축이지 "학생을 식별한다"의 축이 아니다. 명부를 특정 화면들의
   부속으로 묶으면 기능 단위 오픈(key_considerations §1)이 오히려 어긋난다.
2. 이 응답은 **이름·원번·학년·반·등록상태뿐**이고 연락처는 넣지 않는다
   (개인정보 최소). 출결 명단·워크북 목록·클리닉 배정·상담 대기열이 이미
   같은 수준(이름+원번)을 각 기능 키 보유자에게 노출하므로, 직원 공통 조회로
   두어도 노출 경계가 넓어지지 않는다.
3. 학생 이름·원번 조회는 어느 직원에게든 필요한 기본 정보다(전화 응대·서류
   대조). 여기서 막으면 현장은 결국 다른 화면을 우회로 쓴다 — 수동 우회를
   막지 않는다는 원칙(key_considerations §5)과도 어긋난다.

전화번호는 **검색 키로만** 쓴다(q 부분일치) — 관리자가 아는 번호로 학생을
찾는 동선은 필요하지만 응답 본문에 되돌려줄 이유는 없다(역방향 조회 방지).

## 필터 계약

- `q`: 이름(users.name)·원번(students.matching_key)·전화(users.phone) 부분일치 OR.
- `enrollment_status`: 값집합(예비등록/등록/퇴원) 밖은 뷰가 400.
- `course_id`: **활성 수강(`수강`)** 기준 — 중단·종료 수강은 그 강좌의 현재
  명부가 아니다(출결 명단 load_roster 와 같은 판정).
- `class_name`: 반 이름(`classes.name`) 부분일치 — 활성 수강의 반 전부가 대상
  (학생↔반은 N:M — FLOW 1-1).
- 등록 상태는 **기본 필터 없음** — 예비등록(전환 대상)·퇴원(이력 확인)이
  이 화면의 주 사용처라 좁히면 갭이 남는다. 좁히기는 호출측 선택.
"""
from django.db.models import Q

from apps.curriculum.models import CourseEnrollment, class_name_subquery
from apps.notifications.models import Notification
from apps.notifications.notification_admin import build_row as notification_row
from apps.payments.models import Order
from apps.payments.payment_admin import build_row as order_row

from .models import Student


def build_queryset(q=None, enrollment_status=None, course_id=None, class_name=None):
    """명부 쿼리셋 — 검증 통과한 파라미터 전제(뷰가 값집합·형변환 담당).

    `select_related("user")` 로 이름 조인을 한 번에 붙이고 반 이름은
    서브쿼리로 붙인다(N+1 금지 — 페이지 크기와 무관하게 목록 쿼리 1회).
    정렬은 student_id 오름차순(페이지네이션 결정성 — 출결 명단 정렬 축과 동일).
    """
    queryset = Student.objects.select_related("user").annotate(
        class_name=class_name_subquery()
    )
    if q:
        queryset = queryset.filter(
            Q(user__name__icontains=q)
            | Q(matching_key__icontains=q)
            | Q(user__phone__icontains=q)
        )
    if enrollment_status:
        queryset = queryset.filter(enrollment_status=enrollment_status)
    if course_id is not None:
        queryset = queryset.filter(
            course_enrollments__course_id=course_id,
            course_enrollments__status=CourseEnrollment.Status.ENROLLED,
        )
    if class_name:
        queryset = queryset.filter(
            course_enrollments__klass__name__icontains=class_name,
            course_enrollments__status=CourseEnrollment.Status.ENROLLED,
        )
    # 수강 조인이 붙는 경우의 행 중복 방어(UQ(student, course)로 실제 중복은
    # 없지만 조인 조건이 늘어도 계약이 깨지지 않게 고정한다).
    return queryset.distinct().order_by("student_id")


def row(student, class_name):
    """명부 행 — 개인정보 최소(연락처·학교·노쇼 등 운영 컬럼 미포함).

    name 은 연결된 users 행에서 취한다 — 계정 발급 전 학생은 null
    (students 에 이름 컬럼이 없다는 accounts 설계 계약).

    반 이름은 학생 행에 없으므로(`Class` 가 원천) 호출측이 넘긴다 — 목록은
    `build_queryset` 의 annotate 값을, 단건은 `class_name_of` 를 쓴다.
    """
    return {
        "student_id": student.student_id,
        "name": student.user.name if student.user else None,
        "login_id": student.user.login_id if student.user else None,
        "matching_key": student.matching_key,
        "grade": student.grade,
        "current_class": class_name,
        "enrollment_status": student.enrollment_status,
    }


def detail(student):
    """학생 상세 — FLOW 2-6 이 한 화면에 모으라고 한 것들.

    목록(`row`)과 달리 **연락처가 실린다.** 고칠 수 있어야 하는 값이고(FLOW 2-6),
    틀린 번호를 눈으로 확인하지 못하면 고칠 수도 없다. 그래서 이 응답만 게이트가
    다르다 — 목록은 직원 공통이지만 상세·수정은 `계정관리` 다.

    발송 내역은 **학부모 앞으로 나간 것도 함께** 본다(FLOW 2-5). 번호 없는 학생의
    계정 안내가 학부모에게 가므로(provisioning), 학생 행만 보면 정작 그 학생의
    아이디가 어디로 갔는지가 빠진다. 교재·결제 행은 결제 관리 화면과 같은 조립을
    쓴다(payment_admin) — 같은 사실을 두 모양으로 만들지 않는다.
    """
    user = student.user
    parents = [
        link.parent
        for link in student.parent_students.select_related("parent__user").order_by("parent_id")
    ]
    orders = (
        Order.objects.filter(student=student)
        .select_related("product", "student__user")
        .prefetch_related("payments")
        .order_by("-order_id")
    )
    notifications = (
        Notification.objects.filter(Q(student=student) | Q(parent__in=parents))
        .select_related("student__user", "parent", "user")
        .order_by("-notif_id")
    )
    return {
        "student_id": student.student_id,
        "name": user.name if user else None,
        "login_id": user.login_id if user else None,
        "matching_key": student.matching_key,
        "phone": user.phone if user else "",
        "grade": student.grade,
        "school": student.school,
        "enrollment_status": student.enrollment_status,
        "parents": [
            {
                "parent_id": parent.parent_id,
                "name": parent.name,
                "phone": parent.phone,
                "login_id": parent.user.login_id if parent.user else None,
            }
            for parent in parents
        ],
        "classes": [
            {
                "class_id": enrollment.klass_id,
                "class_name": enrollment.klass.name if enrollment.klass else None,
                "course_name": enrollment.course.name,
                "status": enrollment.status,
            }
            for enrollment in (
                CourseEnrollment.objects.filter(student=student)
                .select_related("klass", "course")
                .order_by("enrollment_id")
            )
        ],
        "orders": [order_row(order) for order in orders],
        "notifications": [notification_row(notification) for notification in notifications],
    }

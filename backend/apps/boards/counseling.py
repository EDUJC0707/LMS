"""결석 상담 서비스 — 대기열·통화 결과 기록·3회 종결 (PRD 3.1.9(1)·6-17·8-18).

**카드 = 통화 시도 1건(행 단위 시도 이력)**: 출결 트리거(grades.attendance_
admin)가 결석 1건당 첫 대기 카드를 만들고, `미연결` 기록 시 이 서비스가
같은 (학생, 결석 회차, 대상)의 **새 대기 카드**를 만들어 대기열에 되돌린다.
시도 횟수는 그 그룹에서 called_at 이 찍힌 행 수로 산출한다 — 스키마 무변경
제약(8차) 아래에서 시도 횟수를 표시할 유일한 원천이 행이고, 행은 감사
이력이기도 하다(누가 언제 몇 번째로 걸었나). 트리거의 중복 금지 검사는
attendance 기준 "행 존재 여부"라 재시도 카드와 충돌하지 않고, 정정 삭제는
"미통화 대기 행만" 지우므로 통화 이력 행은 보존된다(3차 계약과 정합).

**3회 시도 후 문자 종결(8-18 확정)**: 당일 학부모 1차 최대 3회 → 3회째도
미연결이면 재시도 카드를 만들지 않고 알림톡(결석 안내+동보 신청 링크)으로
종결한다. 이번 슬라이스는 **기록만** — notifications 행(status `대기`)을
남기고 실제 발송은 알림톡 채널 연동 시 발송 배치가 집어간다(clinic_admin
과 동일 임시 정책).

**동보 여부는 기록만**: makeup_requested 체크는 상담기록 소관이고 영상
지급은 동보 체크 API(영상지급관리 키 — grades.MakeupCheckView)가 담당한다
(3차 슬라이스 기능 키 판단과 동일 축).
"""
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from apps.accounts.models import ParentStudent
from apps.notifications.models import Notification

from .models import AbsenceCounseling

# 학부모 1차 통화 최대 시도 횟수(8-18) — 도달 시 문자 종결.
MAX_CALL_ATTEMPTS = 3


class CounselingError(Exception):
    """규칙 위반 — message 를 뷰가 400 본문으로 옮긴다(ClinicError 선례)."""

    def __init__(self, message):
        super().__init__(message)
        self.message = message


def _attempt_filter(card):
    """같은 통화 그룹(학생·결석 회차·대상) — 시도 횟수 산출 단위."""
    return Q(
        student_id=card.student_id,
        attendance_id=card.attendance_id,
        target=card.target,
    )


def attempts_so_far(card):
    """이 그룹에서 이미 수행된 통화 시도 수(called_at 찍힌 행)."""
    return AbsenceCounseling.objects.filter(
        _attempt_filter(card), called_at__isnull=False
    ).count()


def queue_rows():
    """대기 카드 목록 — 시도 횟수·결석일 동봉(전화 화면 자료)."""
    cards = (
        AbsenceCounseling.objects.filter(status=AbsenceCounseling.Status.PENDING)
        .select_related("student__user", "attendance__session")
        .order_by("created_at", "counsel_id")
    )
    cards = list(cards)
    # 그룹별 시도 수 1쿼리 집계(카드마다 COUNT 재실행 방지).
    counts = {}
    if cards:
        grouped = (
            AbsenceCounseling.objects.filter(
                called_at__isnull=False,
                student_id__in={c.student_id for c in cards},
            )
            .values("student_id", "attendance_id", "target")
            .annotate(n=Count("counsel_id"))
        )
        counts = {
            (g["student_id"], g["attendance_id"], g["target"]): g["n"] for g in grouped
        }
    return [
        _queue_row(c, counts.get((c.student_id, c.attendance_id, c.target), 0))
        for c in cards
    ]


def _queue_row(card, attempts):
    student = card.student
    session = card.attendance.session if card.attendance else None
    return {
        "counsel_id": card.counsel_id,
        "student": {
            "student_id": student.student_id,
            "name": student.user.name if student.user else None,
            "unique_id": student.unique_id,
        },
        "target": card.target,
        "status": card.status,
        "attempts": attempts,
        "absence_date": session.session_date.isoformat() if session else None,
        "created_at": timezone.localtime(card.created_at).isoformat(),
    }


def record_call(card, result, fields, actor):
    """통화 결과 기록 — 연결→완료 / 미연결→재시도 카드 또는 문자 종결.

    반환: (card, attempts, next_card|None, closed_by_sms). 한 트랜잭션 —
    카드 확정과 재시도 카드/종결 기록은 함께 반영되거나 함께 무효다.
    """
    if card.status != AbsenceCounseling.Status.PENDING:
        raise CounselingError("이미 처리된 상담 카드입니다.")
    now = timezone.now()
    with transaction.atomic():
        card.called_at = now
        card.counselor = actor
        for name in ("absence_reason", "call_memo", "follow_up_action"):
            if name in fields:
                setattr(card, name, fields[name])
        if "makeup_requested" in fields:
            card.makeup_requested = fields["makeup_requested"]
        connected = result == "연결"
        card.status = (
            AbsenceCounseling.Status.COMPLETED
            if connected
            else AbsenceCounseling.Status.UNREACHED
        )
        card.save()
        if connected:
            return card, attempts_so_far(card), None, False
        attempts = attempts_so_far(card)
        if attempts < MAX_CALL_ATTEMPTS:
            next_card = AbsenceCounseling.objects.create(
                student=card.student,
                attendance=card.attendance,
                target=card.target,
                status=AbsenceCounseling.Status.PENDING,
            )
            return card, attempts, next_card, False
        _record_sms_closure(card)
        return card, attempts, None, True


def _record_sms_closure(card):
    """3회 종결 — 알림톡(결석 안내+동보 링크) **기록만**(모듈 docstring)."""
    for link in ParentStudent.objects.filter(student=card.student):
        Notification.objects.create(
            parent=link.parent,
            channel=Notification.Channel.KAKAO,
            type=Notification.Type.ABSENCE_COUNSEL,
            title="결석 안내(전화 미연결 종결)",
            ref_type="absence_counseling",
            ref_id=card.counsel_id,
            status=Notification.Status.PENDING,
        )

"""결석 상담 서비스 — 대기열·통화 결과 기록·3회 종결 (PRD 3.1.9(1)·6-17·8-18).

**카드 = 통화 시도 1건(행 단위 시도 이력)**: 출결 트리거(grades.attendance_
admin)가 결석 1건당 첫 대기 카드를 만들고, `미연결` 기록 시 이 서비스가
같은 (학생, 결석 회차, 대상)의 **새 대기 카드**를 만들어 대기열에 되돌린다.
시도 횟수는 그 그룹에서 called_at 이 찍힌 행 수로 산출한다 — 스키마 무변경
제약(8차) 아래에서 시도 횟수를 표시할 유일한 원천이 행이고, 행은 감사
이력이기도 하다(누가 언제 몇 번째로 걸었나). 트리거의 중복 금지 검사는
attendance 기준 "행 존재 여부"라 재시도 카드와 충돌하지 않고, 정정 삭제는
"미통화 대기 행만" 지우므로 통화 이력 행은 보존된다(3차 계약과 정합).

**3회는 마감이 아니라 신호다(2026-08-12 확정)**: 3회째 미연결이면 재시도
카드를 만들지 않지만 **알림톡이 저절로 나가지는 않는다.** "당일, 늦어도
다음날"(PRD 3.1.9)은 운영 목표지 시스템 마감이 아니라, 카드는 닫을 때까지
남는다 — 조교가 더 걸 수도 있고 3회 전에 `종결`로 닫을 수도 있다.
발송은 `notify()` 를 부르는 **버튼**이 하고, 그 전까지 닫힌 카드는 대기열에
남아 누를 자리를 유지한다(`queue_rows`). 발송 자체는 `notifications.sending.
queue` 가 행을 남기고 **커밋 뒤** 태스크를 건다(clinic_admin 과 동일).

**동보 여부는 기록만**: makeup_requested 체크는 상담기록 소관이고 영상
지급은 동보 체크 API(영상지급관리 키 — grades.MakeupCheckView)가 담당한다
(3차 슬라이스 기능 키 판단과 동일 축).
"""
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from apps.accounts.models import ParentStudent
from apps.notifications.models import Notification
from apps.notifications.sending import queue as queue_notification

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


def _notified_ids(cards):
    """이미 결석 안내가 걸린 카드 — 발송 여부는 Notification 행으로 판단한다.

    별도 컬럼을 두지 않는 이유: 발송 사실은 이미 notifications 도메인이 갖고
    있고, 여기 플래그를 하나 더 두면 두 곳이 갈릴 수 있다.
    """
    return set(
        Notification.objects.filter(
            ref_type="absence_counseling",
            ref_id__in=[c.counsel_id for c in cards],
        ).values_list("ref_id", flat=True)
    )


def queue_rows():
    """대기 카드 + **안내를 아직 안 보낸 닫힌 카드** — 시도 횟수·결석일 동봉.

    닫힌 카드를 남기는 이유(2026-08-12): 알림톡이 버튼이 된 이상 닫자마자
    목록에서 빠지면 누를 자리가 없어지고, 학부모는 아무 연락도 못 받는다.
    안내가 나가면 그때 빠진다.
    """
    cards = (
        AbsenceCounseling.objects.filter(
            Q(status=AbsenceCounseling.Status.PENDING)
            | Q(status=AbsenceCounseling.Status.UNREACHED)
        )
        .select_related("student__user", "attendance__session")
        .order_by("created_at", "counsel_id")
    )
    cards = list(cards)
    # 닫힌 카드는 안내 전까지만 남긴다. 재시도 카드가 생긴 미연결 행은
    # 이미 다음 카드가 대기 중이므로 목록에 두 번 나오지 않게 걷어낸다.
    notified = _notified_ids(cards)
    retried = set(
        AbsenceCounseling.objects.filter(
            status=AbsenceCounseling.Status.PENDING
        ).values_list("student_id", "attendance_id", "target")
    )
    cards = [
        c
        for c in cards
        if c.status == AbsenceCounseling.Status.PENDING
        or (
            c.counsel_id not in notified
            and (c.student_id, c.attendance_id, c.target) not in retried
        )
    ]
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


def _queue_row(card, attempts):  # noqa: D401
    student = card.student
    session = card.attendance.session if card.attendance else None
    return {
        "counsel_id": card.counsel_id,
        "student": {
            "student_id": student.student_id,
            "name": student.user.name if student.user else None,
            "login_id": student.user.login_id if student.user else None,
            "matching_key": student.matching_key,
        },
        "target": card.target,
        "status": card.status,
        "attempts": attempts,
        # 닫혔는데 안내가 아직 안 나간 카드 — 화면이 발송 버튼을 띄우는 자리.
        "awaiting_notice": card.status == AbsenceCounseling.Status.UNREACHED,
        "absence_date": session.session_date.isoformat() if session else None,
        "created_at": timezone.localtime(card.created_at).isoformat(),
    }


def record_call(card, result, fields, actor):
    """통화 결과 기록 — 연결→완료 / 미연결→재시도 카드 / 종결→닫음.

    반환: (card, attempts, next_card|None, closed). 한 트랜잭션 —
    카드 확정과 재시도 카드 생성은 함께 반영되거나 함께 무효다.

    **알림톡은 여기서 나가지 않는다**(2026-08-12 확정). 3회는 "닫아도 된다"는
    신호일 뿐이고 발송은 `notify()` 를 부르는 버튼이 한다 — 조교가 창을 넘겨
    더 걸 수도, 3회 전에 닫을 수도 있어서 기계가 시점을 못 정한다.
    """
    if card.status != AbsenceCounseling.Status.PENDING:
        raise CounselingError("이미 처리된 상담 카드입니다.")
    closed_manually = result == "종결"
    with transaction.atomic():
        # 종결은 "더 안 건다"는 선언이라 통화 시각을 찍지 않는다 — 찍으면
        # 걸지도 않은 시도가 카운트에 들어간다.
        if not closed_manually:
            card.called_at = timezone.now()
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
        attempts = attempts_so_far(card)
        if connected or closed_manually:
            return card, attempts, None, closed_manually
        if attempts < MAX_CALL_ATTEMPTS:
            next_card = AbsenceCounseling.objects.create(
                student=card.student,
                attendance=card.attendance,
                target=card.target,
                status=AbsenceCounseling.Status.PENDING,
            )
            return card, attempts, next_card, False
        return card, attempts, None, True


def open_card(student, attendance, target):
    """새 통화 카드 — 학생 2차를 조교가 버튼으로 여는 자리(8-18).

    자동 생성하지 않는 이유: "학부모 선에서 해결 안 됐다"를 기계가 판정할
    근거가 없다(통화 결과는 받음/안 받음뿐). `target` 만 갈아 끼우면 되므로
    학부모 재시도와 같은 자리를 쓴다.
    """
    if AbsenceCounseling.objects.filter(
        student=student,
        attendance=attendance,
        target=target,
        status=AbsenceCounseling.Status.PENDING,
    ).exists():
        raise CounselingError("이미 대기 중인 카드가 있습니다.")
    return AbsenceCounseling.objects.create(
        student=student,
        attendance=attendance,
        target=target,
        status=AbsenceCounseling.Status.PENDING,
    )


def notify(card):
    """닫힌 카드에서 결석 안내(+동보 신청 링크)를 보낸다 — 버튼이 부른다."""
    if card.status != AbsenceCounseling.Status.UNREACHED:
        raise CounselingError("닫힌 상담 카드에서만 보낼 수 있습니다.")
    links = list(ParentStudent.objects.filter(student=card.student))
    if not links:
        raise CounselingError("연결된 학부모가 없습니다.")
    for link in links:
        queue_notification(
            parent=link.parent,
            channel=Notification.Channel.KAKAO,
            type=Notification.Type.ABSENCE_COUNSEL,
            title="결석 안내(전화 미연결 종결)",
            ref_type="absence_counseling",
            ref_id=card.counsel_id,
        )
    return len(links)

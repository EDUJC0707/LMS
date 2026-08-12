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
from django.utils import timezone

from apps.accounts.models import ParentStudent
from apps.notifications.models import Notification
from apps.notifications.sending import queue as queue_notification

from . import channeltalk
from .models import AbsenceCounseling

# 학부모 1차 통화 최대 시도 횟수(8-18) — 도달 시 문자 종결.
MAX_CALL_ATTEMPTS = 3


class CounselingError(Exception):
    """규칙 위반 — message 를 뷰가 400 본문으로 옮긴다(ClinicError 선례)."""

    def __init__(self, message):
        super().__init__(message)
        self.message = message


def attempts_so_far(card):
    """조교가 넣은 시도 횟수. 행 수로 세지 않는다 — 모델 주석 참조."""
    return card.attempts


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
    """대기 카드 + **안내를 아직 안 보낸 닫힌 카드**.

    닫힌 카드를 남기는 이유(2026-08-12): 문자가 버튼이 된 이상 닫자마자 목록에서
    빠지면 누를 자리가 없어지고, 학부모는 아무 연락도 못 받는다.
    보낸 뒤에도 카드는 남는다 — 문자만 다시 못 보낼 뿐 통화는 더 걸 수 있다.
    """
    cards = list(
        AbsenceCounseling.objects.filter(
            status__in=(
                AbsenceCounseling.Status.PENDING,
                AbsenceCounseling.Status.UNREACHED,
            )
        )
        .select_related("student__user", "attendance__session")
        .order_by("created_at", "counsel_id")
    )
    notified = _notified_ids(cards)
    return [_queue_row(c, c.attempts, c.counsel_id in notified) for c in cards]


def _queue_row(card, attempts, notified=False):  # noqa: D401
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
        # 문자는 한 번만 — 보냈으면 화면이 버튼을 끈다.
        "notified": notified,
        "absence_date": session.session_date.isoformat() if session else None,
        "created_at": timezone.localtime(card.created_at).isoformat(),
    }


def record_call(card, result, fields, actor):
    """카드 저장 — 시도 횟수·메모·통화 참조. 결과가 있으면 카드를 닫는다.

    반환: (card, attempts, None, closed).

    **재시도 카드를 만들지 않는다**(2026-08-12). 예전에는 `미연결` 마다 새 행을
    만들어 그 수를 세었는데, 이제 횟수는 조교가 넣는 숫자다 — 화면이 채널톡
    통화 목록을 보여주고 그중 몇 건이 우리 시도인지 사람이 확정한다.

    **알림톡은 여기서 안 나간다.** 3회는 "문자 보내도 된다"는 신호일 뿐이고
    발송은 `notify()` 를 부르는 버튼이 한다. 4회째도 걸 수 있다.
    """
    if card.status != AbsenceCounseling.Status.PENDING:
        raise CounselingError("이미 처리된 상담 카드입니다.")
    if "attempts" in fields:
        attempts = fields["attempts"]
        if not isinstance(attempts, int) or isinstance(attempts, bool) or attempts < 0:
            raise CounselingError("시도 횟수는 0 이상의 정수여야 합니다.")
        card.attempts = attempts
    with transaction.atomic():
        card.counselor = actor
        for name in ("absence_reason", "call_memo", "follow_up_action"):
            if name in fields:
                setattr(card, name, fields[name])
        if "makeup_requested" in fields:
            card.makeup_requested = fields["makeup_requested"]
        # 조교가 화면에서 고른 통화 — 있을 때만 박는다. 개인 전화로 걸었으면
        # 채널톡에 로그가 없고, 그래도 시도 기록 자체는 남아야 한다.
        ref = (fields.get("provider_ref") or "").strip()
        if ref:
            card.provider = AbsenceCounseling.Provider.CHANNELTALK
            card.provider_ref = ref
            card.call_transcript = _fetch_transcript(ref)
        # 결과를 안 주면 횟수만 저장하고 카드는 열어 둔다 — 조교가 아직 거는 중이다.
        if result in ("연결", "미연결", "종결"):
            card.called_at = timezone.now() if result == "연결" else card.called_at
            card.status = (
                AbsenceCounseling.Status.COMPLETED
                if result == "연결"
                else AbsenceCounseling.Status.UNREACHED
            )
        card.save()
    closed = card.status != AbsenceCounseling.Status.PENDING
    return card, card.attempts, None, closed


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


def _fetch_transcript(user_chat_id):
    """전사를 받아 한 덩어리 글로. 실패해도 기록 자체는 저장돼야 한다.

    채널톡이 느리거나 죽었다고 통화 기록을 못 남기면 조교가 다시 걸어야 하는
    것으로 읽힌다 — 여기서 막을 값어치가 없다. 나중에 전사 조회로 다시 볼 수 있다.
    """
    try:
        lines = channeltalk.transcript(user_chat_id)
    except Exception:  # noqa: BLE001 — 업체 장애가 기록을 막지 않는다
        return ""
    return "\n".join(f"{line['speaker']}: {line['said']}" for line in lines)


def phone_for(card):
    """이 카드로 걸어야 할 번호 — 대상에 따라 학부모/학생.

    학생 번호는 `users.phone` 에 있다(students 에는 연락처 컬럼이 없다).
    학부모가 여럿이면 첫 연결을 쓴다 — 채널톡 로그는 번호로만 맞출 수 있어서
    어차피 같은 번호면 같은 결과다.
    """
    if card.target == AbsenceCounseling.Target.STUDENT:
        return card.student.user.phone if card.student.user else ""
    link = ParentStudent.objects.filter(student=card.student).select_related("parent").first()
    return link.parent.phone if link else ""


def already_notified(card):
    """안내를 이미 보냈나 — 발송 사실은 notifications 도메인이 갖고 있다."""
    return Notification.objects.filter(
        ref_type="absence_counseling", ref_id=card.counsel_id
    ).exists()


def notify(card):
    """결석 안내(+동보 신청 링크) — 3회부터, 한 번만.

    보낸 뒤에도 카드는 살아 있다(2026-08-12): 문자만 다시 못 보낼 뿐 통화는
    더 걸 수 있고, 그래서 시도 횟수는 계속 올라간다.
    """
    if card.attempts < MAX_CALL_ATTEMPTS:
        raise CounselingError(f"{MAX_CALL_ATTEMPTS}회부터 보낼 수 있습니다.")
    if already_notified(card):
        raise CounselingError("이미 보냈습니다.")
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

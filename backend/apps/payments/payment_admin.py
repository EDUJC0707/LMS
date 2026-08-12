"""관리자 교재 결제 조회 — 필터 해석·행 조립 (PRD 3.1.5).

**이 조회가 없으면 배부할 사람을 고를 수 없다.** as-is 가 *"결제내역 확인 후
배부"* 이고, 결제선생에서 동기화된 상태가 DB 에만 쌓이면 그 확인 단계가 통째로
빈다.

필터 해석은 여기서 끝낸다(뷰는 게이트·상태 코드 매핑만 — notification_admin·
clinic_admin 선례). 값집합 밖 입력은 빈 목록이 아니라 **오류**다: `status=결제
완료함` 같은 오타가 빈 목록으로 돌아오면 "결제가 하나도 없다"로 읽혀 정반대의
판단을 부른다.

**기간은 `ordered_at` 축이다.** `paid_at` 은 미결제 행에서 NULL 이라 범위
필터에 쓰면 정작 찾아야 할 미결제 건이 통째로 빠진다.
"""
import datetime
import logging

from django.db import transaction
from django.utils import timezone

from apps.notifications.models import Notification
from apps.notifications.sending import queue

from .models import Order, Payment
from .provider import get_adapter

logger = logging.getLogger(__name__)


class PaymentQueryError(Exception):
    """필터 입력 오류 — message 를 뷰가 400 본문으로 옮긴다."""

    def __init__(self, message):
        super().__init__(message)
        self.message = message


def build_queryset(params):
    """조회 파라미터 → 정렬된 queryset. 잘못된 값은 `PaymentQueryError`."""
    queryset = Order.objects.select_related("student__user", "product").prefetch_related(
        "payments"
    )

    status = params.get("status")
    if status:
        if status not in set(Order.Status.values):
            raise PaymentQueryError("상태 값이 올바르지 않습니다.")
        queryset = queryset.filter(status=status)

    student_id = _parse_id(params.get("student_id"), "student_id")
    if student_id is not None:
        queryset = queryset.filter(student_id=student_id)

    product_id = _parse_id(params.get("product_id"), "product_id")
    if product_id is not None:
        queryset = queryset.filter(product_id=product_id)

    is_billed = _parse_bool(params.get("is_billed"), "is_billed")
    if is_billed is not None:
        queryset = queryset.filter(is_billed=is_billed)

    date_from = _parse_date(params.get("from"), "from")
    if date_from is not None:
        queryset = queryset.filter(ordered_at__gte=_start_of(date_from))

    date_to = _parse_date(params.get("to"), "to")
    if date_to is not None:
        # 끝 날짜는 그날을 포함한다 — 관리자가 오늘까지 보려고 오늘을 적는다.
        queryset = queryset.filter(
            ordered_at__lt=_start_of(date_to + datetime.timedelta(days=1))
        )

    return queryset.order_by("-ordered_at", "-order_id")


def build_row(order):
    return {
        "order_id": order.order_id,
        "student": _student(order),
        "product_name": order.product.name,
        "product_id": order.product_id,
        "amount": order.amount,
        "status": order.status,
        "is_billed": order.is_billed,
        "charge_trigger": order.charge_trigger,
        "billed_to_phone": order.billed_to_phone,
        "ordered_at": _localized(order.ordered_at),
        "billed_at": _localized(order.billed_at),
        "paid_at": _localized(order.paid_at),
        "delivered_at": _localized(order.delivered_at),
        "payment": _latest_payment(order),
    }


def _student(order):
    """표시용 학생 한 덩어리.

    students 에 name 컬럼이 없다 — 이름은 users 행이 든다. 계정 발급 전이면
    비어 있으므로 **원번으로 떨어진다**(관리자가 지면에서 쓰는 값이라 빈
    이름보다 낫다 — notification_admin `_target` 과 같은 처리).
    """
    student = order.student
    name = student.user.name if student.user else ""
    return {
        "id": order.student_id,
        "name": name or student.matching_key,
        "matching_key": student.matching_key,
    }


def _latest_payment(order):
    """가장 최근 결제 트랜잭션 요약. 없으면 None(미결제 건).

    **대사(reconciliation)의 근거가 `external_ref`** 다 — 업체 승인번호가 안
    보이면 결제선생 화면과 우리 목록을 맞춰 볼 수단이 없다. 업체 종속 컬럼을
    만들지 않는 대신 이 중립 참조 하나를 반드시 내린다(Payment 모델 계약).
    """
    payments = sorted(order.payments.all(), key=lambda p: p.payment_id)
    if not payments:
        return None
    payment = payments[-1]
    return {
        "payment_id": payment.payment_id,
        "provider": payment.provider,
        "status": payment.status,
        "amount": payment.amount,
        "external_ref": payment.external_ref,
        "paid_at": _localized(payment.paid_at),
        "synced_at": _localized(payment.synced_at),
    }


def cancel_order(order, *, reason, now=None):
    """주문을 취소한다 — 업체에 무엇을 부를지는 **상태가 정한다**.

    | 주문 상태 | 업체 호출 | 이유 |
    |---|---|---|
    | 결제완료·배부완료 | `/bill/cancel` | 승인된 건은 승인취소다 |
    | 미결제 + 청구서 발송됨 | `/bill/destroy` | 승인 전이라 취소가 안 먹는다(파기) |
    | 미결제 + 미발송 | 없음 | 업체에 청구서가 존재한 적이 없다 |

    마지막 줄이 중요하다 — 없는 청구서에 파기를 걸면 `BILL_003` 으로 실패하고,
    그러면 **우리 쪽 오등록 주문을 영영 못 지운다.**

    업체 호출은 트랜잭션 밖이다(billing 과 같은 이유). 업체가 성공한 뒤에야
    우리 행을 접는다 — 반대 순서면 우리는 취소인데 업체는 살아 있는 상태가 난다.
    """
    now = now or timezone.now()
    if order.status == Order.Status.CANCELLED:
        raise PaymentQueryError("이미 취소된 주문입니다.")
    if not reason or not str(reason).strip():
        # §5: 파괴적 작업은 이력이 남아야 한다. 사유 없는 환불은 받지 않는다.
        raise PaymentQueryError("취소 사유를 입력해 주세요.")

    bill_ref = str(order.order_id)
    if order.status in (Order.Status.PAID, Order.Status.DELIVERED):
        get_adapter().cancel_bill(bill_ref, amount=order.amount, reason=str(reason))
    elif order.is_billed:
        get_adapter().destroy_bill(bill_ref, amount=order.amount)

    was_paid = order.status in (Order.Status.PAID, Order.Status.DELIVERED)
    with transaction.atomic():
        order.status = Order.Status.CANCELLED
        order.save(update_fields=["status"])
        # 결제 트랜잭션도 함께 접는다 — 주문만 취소하면 대사에서 완료 건이 남는다.
        order.payments.exclude(status=Payment.Status.CANCELLED).update(
            status=Payment.Status.CANCELLED, synced_at=now
        )
        _notify_cancelled(order, was_paid=was_paid)
    return order


def _notify_cancelled(order, *, was_paid):
    """취소를 청구서 받은 사람에게 알린다 — **업체는 알려 주지 않는다.**

    결제선생은 청구할 때만 알림톡을 보낸다(`/bill/cancel` 에는 통지 항목이
    아예 없다 — 2026-08-11 확인). 그대로 두면 학부모 입장에서 돈이 조용히
    돌아오거나 청구서가 조용히 사라진다.

    **청구서를 보낸 적이 없으면 알리지 않는다** — 받은 적 없는 청구의 취소는
    학부모에게 아무 의미가 없다(오등록 정리가 그 사람 알림함에 쌓일 뿐).

    받는 사람은 **청구서를 받은 쪽**이다(`billed_to_parent`). 학생이 자기
    번호로 받았으면 학생에게 간다.

    **8-17 대기 중**: 알림톡 템플릿이 승인 전이라 발송 자체는 실패하고 사유가
    남는다. 행은 남으므로 승인 뒤에 사람이 되짚을 수 있다(조용한 성공 금지).
    """
    if not order.is_billed:
        return
    what = "환불되었습니다" if was_paid else "취소되었습니다"
    try:
        queue(
            type=Notification.Type.PAYMENT,
            channel=Notification.Channel.KAKAO,
            student=None if order.billed_to_parent_id else order.student,
            parent=order.billed_to_parent,
            title="교재 결제",
            body=f"{order.product.name} {order.amount:,}원 결제가 {what}.",
            ref_type="orders",
            ref_id=order.order_id,
        )
    except Exception:
        # **알림 실패가 환불을 뒤엎지 못하게 한다.** 2026-08-12 운영 실측:
        # 취소가 업체·DB 에 다 반영된 뒤 디스패치가 Celery 브로커를 못 찾아
        # 터졌고(운영에 워커가 아직 없다), 트랜잭션은 이미 커밋된 뒤라
        # **돈은 돌아갔는데 화면에는 실패**가 떴다.
        #
        # 삼켜도 조용한 실패가 아니다 — `queue` 는 디스패치 **전에** 알림 행을
        # 만들므로 그 행이 남고 재발송 배치가 집어 간다. 여기서는 사유만 남긴다.
        logger.exception("결제 취소 알림을 걸지 못했습니다 (order=%s)", order.order_id)


def mark_delivered(order, *, now=None):
    """교재 배부완료 처리(PRD 3.1.5 as-is "결제내역 확인 후 배부").

    **결제완료 건만** 넘어간다. 미결제를 배부완료로 올리면 무료로 나간 교재가
    장부에서 사라진다.

    이미 배부완료면 **시각을 덮지 않는다** — 실제로 배부한 때가 기록이고,
    두 번 누른 때가 아니다.
    """
    now = now or timezone.now()
    if order.status == Order.Status.DELIVERED:
        return order
    if order.status != Order.Status.PAID:
        raise PaymentQueryError("결제완료된 주문만 배부할 수 있습니다.")
    order.status = Order.Status.DELIVERED
    order.delivered_at = now
    order.save(update_fields=["status", "delivered_at"])
    return order


def _parse_id(raw, label):
    if raw in (None, ""):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise PaymentQueryError(f"{label} 값이 올바르지 않습니다.") from None


def _parse_bool(raw, label):
    if raw in (None, ""):
        return None
    lowered = str(raw).strip().lower()
    if lowered in {"true", "1"}:
        return True
    if lowered in {"false", "0"}:
        return False
    raise PaymentQueryError(f"{label} 값이 올바르지 않습니다.")


def _parse_date(raw, label):
    if raw in (None, ""):
        return None
    try:
        return datetime.date.fromisoformat(raw)
    except ValueError:
        raise PaymentQueryError(f"{label} 날짜 형식이 올바르지 않습니다.") from None


def _start_of(day):
    """그 날 00:00(Asia/Seoul) — 서버 시계 기준으로 하루 경계를 잡는다."""
    return timezone.make_aware(datetime.datetime.combine(day, datetime.time.min))


def _localized(value):
    return timezone.localtime(value).isoformat() if value else None

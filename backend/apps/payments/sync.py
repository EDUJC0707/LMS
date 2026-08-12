"""결제 상태 동기화 — 업체가 진실이고 우리 행은 그 사본이다 (PRD 3.1.5).

*"결제 상태는 결제선생 데이터를 LMS와 동기화하여 반영"* 이 요구이고, 이
모듈이 그 반영을 하는 유일한 자리다. 콜백 수신도 나중에 붙을 폴링 배치도
여기를 부른다 — 두 경로가 각자 상태를 옮기면 판정이 갈린다.

**콜백 본문을 믿지 않는다.** 업체 콜백에는 서명·검증 수단이 문서화돼 있지
않다(2026-08-05 조사). 본문을 그대로 반영하면 아무나 `billId` 를 찍어 POST
하는 것으로 결제가 완료로 넘어가고 교재가 공짜로 나간다. 그래서 콜백은
**"가서 확인해 보라"는 신호로만** 쓰고 상태는 `read_bill` 로 되묻는다.

**상태는 뒤로 가지 않는다.** 배부완료까지 간 주문에 승인 콜백이 늦게 도착해도
결제완료로 되돌리지 않는다 — 배부완료는 결제완료 다음 단계라서, 되돌리면
배부한 사실이 사라진다.
"""
from django.db import transaction
from django.utils import timezone

from .models import Order, Payment
from .provider import BillState, get_adapter


class UnknownBill(Exception):
    """우리 장부에 없는 청구 번호 — 조용히 삼키지 않는다(호출측이 알린다)."""


#: 결제 완료보다 뒤에 있는 주문 상태 — 동기화가 되돌리지 않는다.
_AFTER_PAID = frozenset({Order.Status.DELIVERED})

#: 업체 상태 → 우리 결제 트랜잭션 상태. `파기` 는 여기 없다 — 주문 쪽 사건이다.
_PAYMENT_STATUS = {
    BillState.PENDING: Payment.Status.PENDING,
    BillState.PAID: Payment.Status.COMPLETED,
    BillState.CANCELLED: Payment.Status.CANCELLED,
}

#: 업체 상태 → 주문 요약 상태.
_ORDER_STATUS = {
    BillState.PENDING: Order.Status.UNPAID,
    BillState.PAID: Order.Status.PAID,
    BillState.CANCELLED: Order.Status.CANCELLED,
    # 파기 = 승인 전 청구서를 없앤 것. 결제 트랜잭션이 성립한 적이 없으므로
    # 주문을 취소로 접는다(Payment.Status 에 값을 더하지 않는다 — 업체
    # 값집합이 중립 모델로 새어 드는 것을 막는 자리).
    BillState.VOIDED: Order.Status.CANCELLED,
}


def sync_order(bill_ref, *, now=None):
    """업체에게 현재 상태를 물어 주문·결제 행에 반영한다. 반영된 Order 를 돌려준다.

    `bill_ref` 는 우리가 발급한 청구 번호(= order_id). 우리 장부에 없으면
    `UnknownBill`, 업체가 안 잡히면 어댑터의 Temporary/PermanentPaymentError 가
    그대로 올라간다(호출측이 재전달 여부를 정한다).
    """
    now = now or timezone.now()
    try:
        order = Order.objects.get(pk=int(bill_ref))
    except (Order.DoesNotExist, TypeError, ValueError):
        raise UnknownBill(str(bill_ref)) from None

    receipt = get_adapter().read_bill(str(order.order_id))

    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order.pk)
        _apply(order, receipt, now)
    return order


def _apply(order, receipt, now):
    payment = _latest_payment(order)
    payment_status = _PAYMENT_STATUS.get(receipt.state)
    if payment_status is not None:
        if payment is None:
            payment = Payment(order=order, amount=receipt.amount or order.amount)
            payment.provider = get_adapter().provider_value
        payment.status = payment_status
        # 업체 참조는 중립 컬럼 하나로만 들어온다(Payment 계약).
        if receipt.external_ref:
            payment.external_ref = receipt.external_ref
        if receipt.paid_at:
            payment.paid_at = receipt.paid_at
        # 언제 맞춰 본 값인지 — 대사에서 "이 행이 최신인가"의 근거다.
        payment.synced_at = now
        payment.save()

    order_status = _ORDER_STATUS.get(receipt.state)
    if order_status is None:
        return
    if order.status in _AFTER_PAID and order_status == Order.Status.PAID:
        # 배부까지 끝난 주문을 결제완료로 되돌리지 않는다(위 docstring).
        return
    fields = []
    if order.status != order_status:
        order.status = order_status
        fields.append("status")
    if receipt.state == BillState.PAID and order.paid_at is None:
        order.paid_at = receipt.paid_at or now
        fields.append("paid_at")
    if fields:
        order.save(update_fields=fields)


def _latest_payment(order):
    """가장 최근 결제 트랜잭션. 청구 개시가 만들어 둔 `대기` 행이 보통 여기 온다.

    **새 행을 함부로 만들지 않는다** — 같은 승인이 두 번 전달되면 행이 둘
    쌓여 대사가 어긋난다(업체 문서에 중복 전달 보장이 없다).
    """
    return order.payments.order_by("payment_id").last()

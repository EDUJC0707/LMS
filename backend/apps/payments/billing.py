"""교재 청구 개시 — 양측 결제 + 중복 차단 (PRD 3.1.5·3.2.5).

학생 경로와 학부모 경로가 **같은 한 함수**를 쓴다. 두 경로가 각자 청구를
만들면 "양측 결제 + sync" 라는 요구가 정확히 그 자리에서 깨진다.

**중복 차단이 이 모듈의 존재 이유다.** 방어는 두 겹이다:
1. 앱 레이어 — 활성 주문이 이미 `is_billed` 면 **업체를 부르지 않고** 저장된
   결제 링크를 그대로 돌려준다. 청구서 1건은 쌤포인트 1건이고, 학부모에게
   같은 청구가 두 번 가면 as-is 의 불만이 그대로 재현된다.
2. DB — 부분 UQ(student, product) WHERE status <> `취소`(Order Meta). 동시
   클릭처럼 선재 검사가 못 잡는 경합의 최종 방어선이다.

**업체 호출이 실패하면 아무것도 청구된 것으로 남기지 않는다.** 청구서가 안
나갔는데 `is_billed` 가 서면 1번 방어가 자기 자신을 막아 **그 학생은 영원히
재청구를 못 받는다**. 그래서 발송 성공 뒤에야 플래그가 선다.
"""
from django.db import transaction
from django.utils import timezone

from .models import Order, Payment
from .provider import get_adapter


class BillingError(Exception):
    """청구 개시 실패 — message 를 뷰가 응답 본문으로 옮긴다."""

    def __init__(self, message):
        super().__init__(message)
        self.message = message


def active_order(student, product):
    """그 학생·그 교재의 활성 주문(취소 아님). 없으면 None — 부분 UQ 와 같은 축."""
    return (
        Order.objects.filter(student=student, product=product)
        .exclude(status=Order.Status.CANCELLED)
        .first()
    )


def start_billing(student, product, *, actor, parent=None, now=None):
    """청구를 개시하고 (order, created) 를 돌려준다.

    - 이미 청구서가 나간 활성 주문이 있으면 **다시 보내지 않고** 그 주문을
      돌려준다(created=False). 어느 경로에서 눌렀든 같다(양측 sync).
    - `parent` 가 있으면 청구서는 학부모 연락처로 간다(billed_to_phone 스냅샷).
      없으면 학생 본인 연락처다.
    - 업체 호출은 트랜잭션 **밖**이다. HTTP 를 트랜잭션 안에서 하면 업체가
      느릴 때 행 잠금이 그만큼 오래 걸린다.
    """
    now = now or timezone.now()

    existing = active_order(student, product)
    if existing is not None and existing.is_billed:
        return existing, False

    recipient_name, phone = _recipient(student, parent)
    if not phone:
        # 번호가 없으면 청구서가 갈 곳이 없다. 업체를 부르기 전에 멈춘다.
        raise BillingError("청구서를 보낼 연락처가 없습니다.")

    # **주문을 만들기 전에 어댑터를 먼저 세운다.** 미설정·경로 오류로 실패할
    # 것이라면 DB 에 아무것도 남기지 않는다 — 누른 적 없는 청구가 관리 화면에
    # `미청구·미결제` 로 쌓인다.
    #
    # 반대로 **발송 실패(업체 거절)는 주문 행을 남긴다.** billId 가 order_id 라
    # 번호를 받으려면 행이 먼저 있어야 하는 순서 제약이고, 남은 행은 `is_billed`
    # 가 false 여서 다음 시도가 그대로 재사용한다(중복이 아니다).
    adapter = get_adapter()

    order = existing or Order.objects.create(
        student=student,
        product=product,
        # 주문 시점 가격 스냅샷 — 교재 가격 변경과 분리된다(Order 계약).
        amount=product.price,
        initiated_by_user=actor,
        billed_to_parent=parent,
        billed_to_phone=phone,
        charge_trigger=Order.ChargeTrigger.MANUAL,
    )

    bill = adapter.send_bill(_build_request(order, recipient_name, phone, product))

    with transaction.atomic():
        order.is_billed = True
        order.billed_at = now
        order.pay_url = bill.pay_url
        order.billed_to_phone = phone
        order.save(update_fields=["is_billed", "billed_at", "pay_url", "billed_to_phone"])
        # 대기 트랜잭션을 미리 만든다 — 승인 콜백이 이 행을 찾아 완료로 옮긴다.
        Payment.objects.create(
            order=order,
            provider=adapter.provider_value,
            status=Payment.Status.PENDING,
            amount=order.amount,
        )
    return order, existing is None


def _build_request(order, recipient_name, phone, product):
    from django.conf import settings

    from .provider import BillRequest

    callback_base = (getattr(settings, "PAYSSAM_CALLBACK_BASE_URL", "") or "").rstrip("/")
    return BillRequest(
        # billId 는 **우리가 정하는 값**이다(업체 발급이 아니다). 취소 후
        # 재청구는 새 Order 행이 되므로 번호가 겹치지 않는다(부분 UQ 와 맞물림).
        bill_ref=str(order.order_id),
        amount=order.amount,
        customer_name=recipient_name,
        phone=phone,
        product_name=product.name,
        callback_url=f"{callback_base}/api/payments/callback",
    )


def _recipient(student, parent):
    """(청구서에 찍을 이름, 받을 번호). 학부모가 지정되면 학부모 쪽이다."""
    if parent is not None:
        name = parent.name or (parent.user.name if parent.user else "") or "학부모"
        return name, (parent.phone or "").strip()
    user = student.user
    name = (user.name if user else "") or student.matching_key
    return name, ((user.phone if user else "") or "").strip()

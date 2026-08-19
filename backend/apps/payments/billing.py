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

**청구 자격 판정도 여기 있다**(FLOW 1-6·2-7). 학생·학부모·관리자 세 경로가 모두
이 함수를 지나므로, 목록만 걸러 두면 `product_id` 를 직접 실어 보내는 요청이
그대로 통과한다. 판정은 둘이다 — ① 그 학생이 듣는 커리의 교재인가 ② 그 반이
결제선생으로 받는 반인가.
"""
import logging

from django.db import transaction
from django.utils import timezone

from apps.curriculum.models import CourseEnrollment
from apps.notifications.models import Notification
from apps.notifications.sending import queue

from .models import Order, Payment
from .provider import get_adapter

logger = logging.getLogger(__name__)


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


def check_billable(student, product):
    """청구해도 되는 짝인지 본다 — 안 되면 `BillingError`(FLOW 1-6·2-7).

    막는 것 둘:
    - **다른 커리의 교재**. 목록은 이미 커리로 좁지만 청구는 `product_id` 를
      본문으로 받으므로 목록을 안 거치고 들어올 수 있다.
    - **결제선생을 안 쓰는 반**. 러셀은 교재값을 학원이 따로 받는다(FLOW 2-7) —
      여기서 안 막으면 조교의 기억이 유일한 안전장치가 되고, 한 번 잘못 누르면
      학부모에게 이중 청구가 나간다.

    반이 안 붙은 수강(`klass` NULL)도 막는다. 결제선생을 쓰는 반이라는 근거가
    없는 것이지 없어도 된다는 뜻이 아니다.
    """
    enrollment = (
        CourseEnrollment.objects.filter(
            student=student,
            course_id=product.course_id,
            status=CourseEnrollment.Status.ENROLLED,
        )
        .select_related("klass")
        .order_by("enrollment_id")
        .first()
        if product.course_id
        else None
    )
    if enrollment is None:
        raise BillingError("이 학생이 듣는 커리의 교재가 아닙니다.")
    if enrollment.klass is None or not enrollment.klass.uses_payssam:
        raise BillingError("결제선생으로 청구하지 않는 반입니다.")


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

    check_billable(student, product)

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
        _notify_billed(order, product)
    return order, existing is None


def _notify_billed(order, product):
    """무엇에 대한 청구인지 알린다(FLOW 3-11 #2).

    **결제선생 문자만으로는 모른다** — 업체 알림톡에는 금액과 링크만 있고 어느
    교재인지가 없다. 받는 사람은 청구서를 받은 쪽이다(`billed_to_parent`,
    없으면 학생 본인 — `_recipient` 와 같은 갈래).

    삼키는 이유는 `payment_admin._notify_cancelled` 와 같다: 청구서는 이미
    업체로 나갔고 트랜잭션은 곧 커밋된다. 여기서 예외가 올라가면 **청구는
    됐는데 화면에는 500** 이 뜬다. 행은 `queue` 가 먼저 만들어 두므로 재발송
    배치가 집어 간다.
    """
    try:
        queue(
            type=Notification.Type.BILLING,
            channel=Notification.Channel.KAKAO,
            student=None if order.billed_to_parent_id else order.student,
            parent=order.billed_to_parent,
            title="교재 청구",
            body=f"{product.name} {order.amount:,}원",
            ref_type="orders",
            ref_id=order.order_id,
        )
    except Exception:
        logger.exception("교재 청구 알림을 걸지 못했습니다 (order=%s)", order.order_id)


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
    """(청구서에 찍을 이름, 받을 번호). 학부모가 지정되면 학부모 쪽이다.

    **이름은 언제나 이 건의 학생에서 나온다**(FLOW 2-4). 학부모 계정의
    `user.name` 은 최초 연결 자녀 기준으로 고정되고(provisioning 의 다자녀 절)
    `Parent.name` 은 설계상 비어 있어서, 그쪽을 쓰면 **둘째 교재 청구서에 첫째
    이름이 찍힌다**. 형제를 묶지 않기로 한 이상(아이디마다 따로 청구가 나간다)
    학부모는 두 건을 이름으로만 가를 수 있고, 같은 교재면 두 문자가 글자 하나
    다르지 않게 된다. 남의 자녀 이름이 실린 청구서라 개인정보 축도 걸린다.
    """
    name = (student.user.name if student.user else "") or student.matching_key
    if parent is not None:
        return f"{name} 학부모", (parent.phone or "").strip()
    user = student.user
    return name, ((user.phone if user else "") or "").strip()

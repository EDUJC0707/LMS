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

from django.utils import timezone

from .models import Order


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

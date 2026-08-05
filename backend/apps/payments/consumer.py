"""교재 결제 소비자 조회 서비스 — 내 결제·배부 상태 (PRD 3.2.5·3.4).

학생 화면과 학부모 화면이 **같은 한 함수**를 쓴다. 두 경로가 각자 목록을
만들면 학생에게는 보이는 주문이 학부모에게는 안 보이는 식으로 갈린다 —
같은 학생의 같은 주문이므로 판정이 갈릴 이유가 없다.

**보이는 범위는 학생 1명의 주문 전부**다. 결제는 자격 게이팅 대상이 아니다 —
예비등록생(미등록)에게 열려 있는 것이 바로 교재 구매라서(PRD §4 상태 기반
노출), 등록 상태로 목록을 좁히지 않는다. 좁혀야 하는 것은 **누구의 주문인가**
뿐이고, 그 판정은 호출측(뷰)이 학생을 해석하는 자리에서 이미 끝나 있다.
"""
from django.utils import timezone

from .models import Order


def _iso(value):
    """aware datetime → Asia/Seoul 로컬 ISO 문자열(2차 슬라이스 표기 선례)."""
    return timezone.localtime(value).isoformat() if value else None


def build_order_list(student):
    """학생 1명의 교재 주문·결제 상태 목록. 최근 청구가 위다.

    `status` 는 주문 상태 요약(미결제→결제완료→배부완료)이고 이것이 화면이
    읽는 값이다(Order 모델 계약 — 결제 트랜잭션은 payments 가 들고 요약은
    orders 가 든다). 취소 건도 내린다 — 재청구가 가능한 상태라 학생·학부모가
    "예전에 취소됐다"를 볼 수 있어야 한다.
    """
    orders = (
        Order.objects.filter(student=student)
        .select_related("product")
        .order_by("-ordered_at", "-order_id")
    )
    return [
        {
            "order_id": order.order_id,
            "product_name": order.product.name,
            "amount": order.amount,
            "status": order.status,
            "ordered_at": _iso(order.ordered_at),
            "paid_at": _iso(order.paid_at),
            "delivered_at": _iso(order.delivered_at),
        }
        for order in orders
    ]

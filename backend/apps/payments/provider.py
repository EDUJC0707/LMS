"""결제 제공자 어댑터 계약 — 업체 교체 가능성의 경계선 (PRD 6-5, key_considerations §4).

**여기가 결제 업체가 들어오는 유일한 문이다.** 모델은 `provider` 값과 중립
외부 참조(`external_ref`)만 알고, "결제선생이 어떤 HTTP 를 어떻게 부르는가"는
이 계약 뒤에 있다. 업체 교체(결제선생 → PG) = `Payment.Provider` 값 추가 +
설정 한 줄이고 스키마는 움직이지 않는다(notifications `channels.py`·clinic
`conferencing.py` 와 같은 축).

**어댑터는 ORM 을 모른다.** 받는 것은 `BillRequest` 하나뿐이다. Order 인스턴스를
그대로 넘기면 업체 코드가 우리 모델 구조를 붙들게 되고, 그 순간 "구현체만 교체"가
성립하지 않는다(어댑터 테스트에 DB 가 필요해지는 것도 같은 증상이다).

**업체 상태 코드는 여기서 끝난다.** 결제선생은 `F/W/C/D` 로 답하지만 그 글자가
앱 레이어로 새어 나오면 PG 로 바꿀 때 값이 안 맞는다. 어댑터가 자기 응답을
`BillState`(중립)로 번역하는 것이 어댑터의 일이다.

**재시도 여부는 예외 종류가 말한다.** 업체 응답 문자열을 호출측이 파싱해 갈리면
업체마다 규칙이 달라져 재시도 정책이 무너진다. 어댑터가 자기 응답을 해석해
`TemporaryPaymentError`(다시 걸어볼 값어치가 있다) / `PermanentPaymentError`(몇
번을 걸어도 같다)로 번역한다.

**기본값은 닫힘이다**(key_considerations §5). `PAYMENT_PROVIDER_BACKEND` 가 비면
청구·조회·취소가 전부 실패한다. 돈이 오가는 경로라 "미설정 = 조용한 성공"이
특히 위험하다 — 청구서는 안 나갔는데 주문만 `청구됨`으로 넘어가면 교재가
공짜로 배부된다.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from django.conf import settings
from django.db import models
from django.utils.module_loading import import_string


class PaymentError(Exception):
    """결제 연동 실패의 뿌리. 직접 쓰지 말고 아래 둘 중 하나를 고른다."""


class TemporaryPaymentError(PaymentError):
    """다시 걸면 될 수 있다 — 타임아웃·5xx·VAN/은행 응답 실패·점검 중."""


class PermanentPaymentError(PaymentError):
    """몇 번을 걸어도 같다 — 키 없음·해시 불일치·중복 청구번호·청구서 없음·미설정."""


class BillState(models.TextChoices):
    """청구서의 중립 상태 — 업체 코드는 어댑터 안에서 여기로 번역된다.

    결제선생 대응(V2 `apprState`): `W`→대기 · `F`→완료 · `C`→취소 · `D`→파기.

    **`파기`는 `Payment` 가 아니라 `Order` 쪽 사건이다.** 승인 전 청구서를
    없앤 것이라 결제 트랜잭션이 성립한 적이 없다 — 앱 레이어에서
    `Order.Status.취소` 로 접고 `Payment.Status` 에는 값을 더하지 않는다
    (업체 값집합이 중립 모델로 새어 드는 것을 막는다).

    `Payment.Status.실패` 에 대응하는 업체 상태는 없다 — 결제선생에서 실패한
    시도는 그냥 미결제로 남는다. 우리 쪽 발송 실패를 기록할 때만 쓴다.
    """

    PENDING = "대기", "대기"
    PAID = "완료", "완료"
    CANCELLED = "취소", "취소"
    VOIDED = "파기", "파기"


@dataclass(frozen=True)
class BillRequest:
    """어댑터가 받는 전부 — 중립 청구 요청.

    - bill_ref: **우리가 정하는** 청구 식별자(`Order` 에서 유도). 업체가
      발급하는 값이 아니다 — 결제선생 `billId` 가 파트너 지정값이라 그렇고,
      PG 로 바뀌어도 "우리 주문을 가리키는 우리 번호"라는 뜻은 같다.
    - phone: 청구서를 받을 번호. 학부모 연락처 스냅샷(`Order.billed_to_phone`).
    - callback_url: 결제 승인 통지가 돌아올 우리 주소. **청구서 단위**로 실린다.
    - expires_at: 청구서 만료. None 이면 업체 기본값에 맡긴다.
    """

    bill_ref: str
    amount: int
    customer_name: str
    phone: str
    product_name: str
    callback_url: str
    expires_at: datetime | None = None


@dataclass(frozen=True)
class Bill:
    """청구서 발송이 돌려주는 것.

    - pay_url: 학생·학부모가 여는 결제 링크. **PRD 3.2.5 의 "임베드"가 여기
      착지한다** — 이 URL 을 LMS 화면 안에서 열어 외부 이탈 없이 결제가 끝난다.
      비면 화면이 조용히 빈 자리를 띄우므로 어댑터는 반드시 채워 돌려준다.
    """

    bill_ref: str
    pay_url: str


@dataclass(frozen=True)
class Receipt:
    """청구서 조회·취소가 돌려주는 것 — `Payment` 행이 받을 값.

    - external_ref: 업체의 승인 거래번호. **중립 컬럼 하나**로만 들어온다
      (`Payment.external_ref`) — 업체 종속 컬럼을 만들지 않기 위한 자리다.
      미결제 건은 아직 승인번호가 없어 None 이고, 그래도 조회는 성립한다.
    """

    bill_ref: str
    state: str
    amount: int
    external_ref: str | None = None
    paid_at: datetime | None = None


class PaymentAdapter(ABC):
    """청구서를 실제로 보내고, 상태를 읽고, 취소·파기하는 구현체."""

    @abstractmethod
    def send_bill(self, request: BillRequest) -> Bill:
        """청구서를 보낸다. 실패하면 Temporary/PermanentPaymentError."""

    @abstractmethod
    def read_bill(self, bill_ref: str) -> Receipt:
        """청구서 현재 상태. 없는 번호는 PermanentPaymentError."""

    @abstractmethod
    def cancel_bill(self, bill_ref: str, *, amount: int, reason: str) -> Receipt:
        """**결제 완료된** 건의 승인취소. 미결제 건은 `destroy_bill` 쪽이다."""

    @abstractmethod
    def destroy_bill(self, bill_ref: str, *, amount: int) -> None:
        """**승인 전** 청구서를 없앤다. 결제된 건은 PermanentPaymentError."""


class FakePaymentAdapter(PaymentAdapter):
    """실제로 보내지 않고 보관만 하는 어댑터 — 로컬 개발·테스트용.

    **운영 기본값이 아니다.** `dev.py` 가 명시적으로 물릴 때만 쓰인다(위
    docstring 의 닫힘 기본값 참조). 운영에 남으면 결제 내역에는 청구 성공만
    쌓이고 학부모는 아무 청구서도 못 받는다.
    """

    sent: list[BillRequest] = []
    _bills: dict[str, Receipt] = {}

    def send_bill(self, request: BillRequest) -> Bill:
        FakePaymentAdapter.sent.append(request)
        FakePaymentAdapter._bills[request.bill_ref] = Receipt(
            bill_ref=request.bill_ref, state=BillState.PENDING, amount=request.amount
        )
        return Bill(
            bill_ref=request.bill_ref,
            pay_url=f"https://fake-payments.invalid/bill/{request.bill_ref}",
        )

    def _get(self, bill_ref: str) -> Receipt:
        receipt = FakePaymentAdapter._bills.get(bill_ref)
        if receipt is None:
            raise PermanentPaymentError(f"청구서를 찾을 수 없습니다: {bill_ref}")
        return receipt

    def read_bill(self, bill_ref: str) -> Receipt:
        return self._get(bill_ref)

    def cancel_bill(self, bill_ref: str, *, amount: int, reason: str) -> Receipt:
        receipt = self._get(bill_ref)
        cancelled = Receipt(
            bill_ref=bill_ref,
            state=BillState.CANCELLED,
            amount=amount,
            external_ref=receipt.external_ref,
        )
        FakePaymentAdapter._bills[bill_ref] = cancelled
        return cancelled

    def destroy_bill(self, bill_ref: str, *, amount: int) -> None:
        self._get(bill_ref)
        FakePaymentAdapter._bills[bill_ref] = Receipt(
            bill_ref=bill_ref, state=BillState.VOIDED, amount=amount
        )


def get_adapter() -> PaymentAdapter:
    """설정된 어댑터 인스턴스. 미설정·경로 오류는 `PermanentPaymentError`.

    캐시하지 않는다 — 생성은 값싸고, 캐시를 두면 설정 교체(운영 롤아웃·테스트
    override)가 조용히 옛 구현체를 계속 쓰는 사고가 난다(channels 선례).
    """
    path = getattr(settings, "PAYMENT_PROVIDER_BACKEND", "")
    if not path:
        raise PermanentPaymentError("결제 제공자가 설정되지 않았습니다.")
    try:
        adapter_class = import_string(path)
    except ImportError as exc:
        raise PermanentPaymentError(f"결제 제공자 구현체를 찾을 수 없습니다: {path}") from exc
    return adapter_class()

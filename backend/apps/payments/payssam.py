"""결제선생(페이민트) 어댑터 — 업체 지식은 전부 이 파일 안에 있다.

모델도 뷰도 "결제선생"을 모른다. 업체 교체(→ PG)는 이런 파일을 하나 더 쓰고
`PAYMENT_PROVIDER_BACKEND` 를 바꾸는 것이 전부다(`provider.py` 계약).

**V2 다. V1 을 보고 짜면 조용히 틀린다.** 2026-08-05 업체 안내로 개발 환경이
`stg.paymint.co.kr` → `sandbox.paymint.co.kr` 로, API 가 V1 → V2 로 올라갔다.
*"이전 안내드린 연동 규격서는 V1 의 개발 사항"* 이므로 V1 문서는 보지 않는다.

**단, 응답 메시지 필드는 문서와 서버가 다르다.** 문서는 V2 가 `msg` 라고
적어 두었는데 샌드박스 실호출은 `message` 로 답한다(2026-08-05 실측 —
`{"code":"BILL_003","message":"청구서를 찾을 수 없습니다.","data":null}`).
그래서 **둘 다 읽는다.** 한쪽만 믿으면 거절 사유가 비어 나가 운영에서
원인을 못 본다. 오류 응답도 **HTTP 200** 으로 오므로 판정 근거는 `code` 다.

**해시가 두 종류다.** `phone` 이 실리면 `{billId},{phone},{price}`, 아니면
`{billId},{price}` 다. 청구서 발송은 phone 이 필수라 **3항**이고, 파기·취소는
phone 을 안 실으므로 **2항**이다. 섞으면 `VALIDATION_002`(해시 불일치)로
거절된다. 출력은 SHA-256 **소문자 hex** 로 보낸다 — 문서가 인코딩을 명시하지
않아 샌드박스 실호출로 확인해야 하는 유일한 값이다.

**재시도 분류**: 길이 막힌 것(타임아웃·5xx·JSON 아닌 응답)과 업체가 일시
오류로 답한 것만 `TemporaryPaymentError` 다. 업체가 정상 응답으로 거절한
것(키·해시·중복 청구번호·포인트 부족)은 다시 걸어도 같으므로 영구 실패다.
**모르는 코드는 영구로 둔다** — 재시도로 두면 거절당한 청구가 계속 다시 나가고,
청구서는 한 건마다 쌤포인트를 태운다.

**`POINT_001`(포인트 부족)은 영구지만 운영 사건이다.** 재시도해도 소용없되
원인이 잔액이라 관리자가 충전해야 풀린다. 조용히 실패로만 남기면 청구가
통째로 멈춘 것을 아무도 모른다(호출측이 이 사유를 사람에게 띄워야 한다).
"""
import datetime
import hashlib
import zoneinfo

import requests
from django.conf import settings

from .provider import (
    Balance,
    Bill,
    BillRequest,
    BillState,
    PaymentAdapter,
    PermanentPaymentError,
    Receipt,
    TemporaryPaymentError,
)

#: 업체 응답을 기다리는 상한(초). 없으면 워커가 무한정 잡혀 있는다.
REQUEST_TIMEOUT_SECONDS = 10

#: V2 성공 코드.
SUCCESS_CODE = "0000"

#: 업체 `cancelReason` 길이 한도 — 넘겨 보내면 거절된다.
CANCEL_REASON_LIMIT = 20

#: 업체 승인 시각(`apprDt`)은 타임존 없는 `YYYYMMDDhhmmss` 다. 국내 서비스라
#: Asia/Seoul 로 읽는다 — naive 로 두면 UTC 로 해석돼 9시간 어긋난다.
_SEOUL = zoneinfo.ZoneInfo("Asia/Seoul")

#: 업체 상태 코드 → 중립 상태. 여기가 F/W/C/D 가 끝나는 자리다.
_STATE_MAP = {
    "W": BillState.PENDING,
    "F": BillState.PAID,
    "C": BillState.CANCELLED,
    "D": BillState.VOIDED,
}

#: 다시 걸어볼 값어치가 있는 업체 코드. **이 목록에 없으면 영구**다.
_TRANSIENT_CODES = frozenset(
    {
        "PAYMENT_001",  # VAN 응답 실패
        "PAYMENT_002",  # 은행 응답 실패
        "BILL_006",  # 발송 가능한 상태가 아님
        "MAINTAINED_METHOD",  # 점검 중
        "ERROR",  # 일반 서버 오류
    }
)


class PayssamAdapter(PaymentAdapter):
    """청구서를 결제선생으로 내보내고 상태를 되읽는다.

    `http_post` 는 테스트가 HTTP 경계 하나만 갈아 끼우기 위한 자리다 —
    기본값은 `requests.post` 이고 운영에서는 그대로 쓴다(aligo 선례).
    """

    provider_value = "결제선생"

    def __init__(self, http_post=None):
        self._http_post = http_post or requests.post

    # -- 계약 구현 ---------------------------------------------------------

    def send_bill(self, request: BillRequest) -> Bill:
        bill = {
            "billId": request.bill_ref,
            # PRD 3.1.5 의 as-is 가 카카오톡 청구서다. URL 형은 알림톡을 안 보낸다.
            "sendType": "TALK",
            "memberName": request.customer_name,
            "phone": request.phone,
            "price": str(request.amount),
            "productName": request.product_name,
            "callbackUrl": request.callback_url,
            "hash": _hash(request.bill_ref, request.amount, phone=request.phone),
        }
        if request.expires_at is not None:
            bill["expireDt"] = request.expires_at.strftime("%Y-%m-%d")
        data = self._call("/bill", bill)
        pay_url = data.get("shortUrl")
        if not pay_url:
            # 응답 계약 위반. 빈 URL 을 흘리면 화면이 조용히 빈 자리를 띄운다.
            raise PermanentPaymentError("청구서 URL 이 응답에 없습니다.")
        return Bill(bill_ref=data.get("billId") or request.bill_ref, pay_url=pay_url)

    def read_bill(self, bill_ref: str) -> Receipt:
        data = self._call("/bill/read", {"billId": bill_ref})
        raw_state = data.get("apprState")
        state = _STATE_MAP.get(raw_state)
        if state is None:
            # 모르는 상태를 대기로 넘기면 미결제로 오해해 재청구가 나간다.
            raise PermanentPaymentError(f"알 수 없는 청구서 상태입니다: {raw_state}")
        return Receipt(
            bill_ref=bill_ref,
            state=state,
            amount=_to_int(data.get("apprPrice")),
            external_ref=data.get("apprNum") or None,
            paid_at=_to_datetime(data.get("apprDt")),
        )

    def cancel_bill(self, bill_ref: str, *, amount: int, reason: str) -> Receipt:
        data = self._call(
            "/bill/cancel",
            {
                "billId": bill_ref,
                "price": str(amount),
                "cancelReason": reason[:CANCEL_REASON_LIMIT],
                "hash": _hash(bill_ref, amount),
            },
        )
        return Receipt(
            bill_ref=bill_ref,
            state=BillState.CANCELLED,
            amount=amount,
            external_ref=data.get("apprNum") or None,
        )

    def destroy_bill(self, bill_ref: str, *, amount: int) -> None:
        self._call(
            "/bill/destroy",
            {"billId": bill_ref, "price": str(amount), "hash": _hash(bill_ref, amount)},
        )

    def read_balance(self) -> Balance | None:
        """쌤포인트 잔액 — **하위사업장(학원) 것**을 읽는다.

        청구서를 태우는 포인트는 발송 주체인 하위사업장 잔액이므로 파트너
        자기 잔액(`/read/remain_count`)이 아니라 이쪽이다.

        `chargeUrl` 을 함께 돌려주는 것이 요점이다 — 관리자가 잔액을 보고
        **그 자리에서** 충전할 수 있어야 한다(자동충전 미사용 결정 2026-08-11).
        """
        data = self._call("/read/merchant/remain_count", None)
        return Balance(
            amount=_to_int(data.get("balance")), charge_url=data.get("chargeUrl") or None
        )

    # -- 전송·해석 ---------------------------------------------------------

    def _call(self, path: str, bill: dict | None) -> dict:
        """유일한 HTTP 지점. 자격증명 3종은 봉투 맨 위, 청구 정보는 `bill` 안이다.

        `bill=None` 은 **청구서가 없는 요청**(잔액 조회)이다. 빈 `bill` 을
        붙여 보내면 업체가 형식 오류로 거절한다.
        """
        body = {
            "apiKey": _required("PAYSSAM_API_KEY", "결제선생 API 키가 설정되지 않았습니다."),
            "member": _required("PAYSSAM_MEMBER_ID", "결제선생 member 가 설정되지 않았습니다."),
            "merchant": _required(
                "PAYSSAM_MERCHANT_ID", "결제선생 merchant 가 설정되지 않았습니다."
            ),
        }
        if bill is not None:
            body["bill"] = bill
        url = _base_url() + path
        try:
            response = self._http_post(url, json=body, timeout=REQUEST_TIMEOUT_SECONDS)
        except requests.RequestException as exc:
            raise TemporaryPaymentError(f"결제선생 요청 실패: {exc}") from exc
        if response.status_code >= 500:
            raise TemporaryPaymentError(f"결제선생 서버 오류: HTTP {response.status_code}")
        if response.status_code >= 400:
            raise PermanentPaymentError(
                f"결제선생 요청이 거절됐습니다: HTTP {response.status_code}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            # 점검 페이지·프록시 오류가 HTML 로 온다 — 나중에 다시 걸면 된다.
            raise TemporaryPaymentError("결제선생 응답을 해석할 수 없습니다.") from exc
        _raise_for_code(payload)
        return payload.get("data") or {}


def _raise_for_code(payload: dict) -> None:
    """거절 사유를 뽑아 종류별 예외로 던진다. 모르는 코드는 영구다.

    **`msg` 와 `message` 를 둘 다 읽는다.** 문서(`preparation/req-res`)는 V2 가
    `msg` 이고 `message` 는 V1 이라고 적어 두었지만, 샌드박스 실호출은 V2
    엔드포인트에서 `message` 로 답한다(2026-08-05 실측):
    `{"code":"BILL_003","message":"청구서를 찾을 수 없습니다.","data":null}`.
    한쪽만 읽으면 거절 사유가 비어 나가 운영에서 원인을 못 본다.
    """
    code = payload.get("code")
    if code == SUCCESS_CODE:
        return
    reason = payload.get("msg") or payload.get("message") or f"코드 {code}"
    if code in _TRANSIENT_CODES:
        raise TemporaryPaymentError(f"결제선생 일시 오류: {reason}")
    raise PermanentPaymentError(f"결제선생 거절: {reason}")


def _hash(bill_ref: str, amount: int, phone: str | None = None) -> str:
    """SHA-256 소문자 hex. phone 이 있으면 3항, 없으면 2항이다."""
    parts = [bill_ref, phone, str(amount)] if phone else [bill_ref, str(amount)]
    return hashlib.sha256(",".join(parts).encode()).hexdigest()


def _base_url() -> str:
    return _required(
        "PAYSSAM_API_BASE_URL", "결제선생 API 주소가 설정되지 않았습니다."
    ).rstrip("/")


def _required(setting_name: str, reason: str) -> str:
    value = (getattr(settings, setting_name, "") or "").strip()
    if not value:
        raise PermanentPaymentError(reason)
    return value


def _to_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _to_datetime(value) -> datetime.datetime | None:
    """`YYYYMMDDhhmmss` → Asia/Seoul aware datetime. 형식이 아니면 None."""
    if not value:
        return None
    try:
        parsed = datetime.datetime.strptime(str(value), "%Y%m%d%H%M%S")
    except ValueError:
        return None
    return parsed.replace(tzinfo=_SEOUL)

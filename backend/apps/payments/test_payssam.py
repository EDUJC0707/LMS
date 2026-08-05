"""결제선생(페이민트) 어댑터 테스트 — V2 기준.

**V1 을 보고 짜면 조용히 틀린다.** 업체가 2026-08-05 에 확정한 것:
개발 환경이 `stg` → `sandbox` 로, API 가 V1 → V2 로 올라갔고 *"이전 안내드린
연동 규격서는 V1 의 개발 사항"* 이다. 두 버전이 **응답 필드 이름부터 다르다**:

| | V1 | **V2** |
|---|---|---|
| 메시지 필드 | `message` | **`msg`** |
| 성공 코드 | `0000` | `0000` |

`message` 를 읽으면 실패 사유가 늘 비어 나가고, 거절당한 청구서의 원인을
운영에서 못 본다. 그래서 여기서 버전을 못 박는다.

또 하나의 조용한 오류 지점은 **해시**다. `phone` 이 있으면
`{billId},{phone},{price}` 이고 없으면 `{billId},{price}` 인데, 청구서 발송은
`phone` 이 필수라 **항상 3항 형식**이다. 2항으로 만들면 `VALIDATION_002`
(해시 불일치)로 전량 거절된다.
"""
import hashlib

from django.test import SimpleTestCase, override_settings
from requests import RequestException

from .payssam import PayssamAdapter
from .provider import (
    BillRequest,
    BillState,
    PermanentPaymentError,
    TemporaryPaymentError,
)

CONFIGURED = {
    "PAYSSAM_API_KEY": "테스트키",
    "PAYSSAM_MEMBER_ID": "테스트멤버",
    "PAYSSAM_MERCHANT_ID": "테스트상점",
    "PAYSSAM_API_BASE_URL": "https://sandbox.example/partner",
}


class FakeResponse:
    def __init__(self, payload=None, status_code=200):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


def ok(data=None):
    return FakeResponse({"code": "0000", "msg": "Success", "data": data or {}})


def recorder(response=None, error=None):
    """호출을 기록하는 가짜 전송기 — HTTP 경계 하나만 대신한다."""
    calls = []

    def post(url, json=None, timeout=None):
        calls.append({"url": url, "json": json, "timeout": timeout})
        if error is not None:
            raise error
        return response if response is not None else ok()

    post.calls = calls
    return post


def bill_request(**kwargs):
    kwargs.setdefault("bill_ref", "1024")
    kwargs.setdefault("amount", 45000)
    kwargs.setdefault("customer_name", "김하늘")
    kwargs.setdefault("phone", "01012345678")
    kwargs.setdefault("product_name", "로직엔제 교재 Vol.1")
    kwargs.setdefault("callback_url", "https://lms.example/api/payments/callback")
    return BillRequest(**kwargs)


@override_settings(**CONFIGURED)
class SendBillTests(SimpleTestCase):
    def test_posts_to_bill_endpoint(self):
        post = recorder(ok({"billId": "1024", "shortUrl": "https://pay.ssam/abc"}))
        PayssamAdapter(http_post=post).send_bill(bill_request())
        self.assertEqual(post.calls[0]["url"], "https://sandbox.example/partner/bill")

    def test_credentials_sit_at_the_envelope_top_not_inside_bill(self):
        post = recorder(ok({"shortUrl": "https://pay.ssam/abc"}))
        PayssamAdapter(http_post=post).send_bill(bill_request())
        body = post.calls[0]["json"]
        self.assertEqual(body["apiKey"], "테스트키")
        self.assertEqual(body["member"], "테스트멤버")
        self.assertEqual(body["merchant"], "테스트상점")
        self.assertNotIn("apiKey", body["bill"])

    def test_bill_fields_map_from_the_neutral_request(self):
        post = recorder(ok({"shortUrl": "https://pay.ssam/abc"}))
        PayssamAdapter(http_post=post).send_bill(bill_request())
        bill = post.calls[0]["json"]["bill"]
        self.assertEqual(bill["billId"], "1024")
        self.assertEqual(bill["memberName"], "김하늘")
        self.assertEqual(bill["phone"], "01012345678")
        self.assertEqual(bill["productName"], "로직엔제 교재 Vol.1")
        self.assertEqual(bill["price"], "45000")
        self.assertEqual(bill["callbackUrl"], "https://lms.example/api/payments/callback")

    def test_send_type_is_kakao_talk(self):
        # PRD 3.1.5 as-is 가 카카오톡 청구서다. URL 형은 알림톡을 안 보낸다.
        post = recorder(ok({"shortUrl": "https://pay.ssam/abc"}))
        PayssamAdapter(http_post=post).send_bill(bill_request())
        self.assertEqual(post.calls[0]["json"]["bill"]["sendType"], "TALK")

    def test_hash_uses_the_three_part_form_with_phone(self):
        # phone 이 실리므로 {billId},{phone},{price} 다. 2항으로 만들면
        # VALIDATION_002(해시 불일치)로 전량 거절된다.
        post = recorder(ok({"shortUrl": "https://pay.ssam/abc"}))
        PayssamAdapter(http_post=post).send_bill(bill_request())
        expected = hashlib.sha256(b"1024,01012345678,45000").hexdigest()
        self.assertEqual(post.calls[0]["json"]["bill"]["hash"], expected)

    def test_returns_the_vendor_short_url_as_the_pay_url(self):
        # PRD 3.2.5 임베드가 여는 주소다. 비면 화면이 빈 자리를 띄운다.
        post = recorder(ok({"billId": "1024", "shortUrl": "https://pay.ssam/abc"}))
        bill = PayssamAdapter(http_post=post).send_bill(bill_request())
        self.assertEqual(bill.pay_url, "https://pay.ssam/abc")
        self.assertEqual(bill.bill_ref, "1024")

    def test_missing_short_url_is_permanent_error(self):
        # 응답 계약 위반 — 다시 걸어도 같다. 조용히 빈 URL 을 흘리지 않는다.
        post = recorder(ok({"billId": "1024"}))
        with self.assertRaises(PermanentPaymentError):
            PayssamAdapter(http_post=post).send_bill(bill_request())

    def test_expire_date_uses_the_vendor_date_format(self):
        import datetime

        post = recorder(ok({"shortUrl": "https://pay.ssam/abc"}))
        PayssamAdapter(http_post=post).send_bill(
            bill_request(expires_at=datetime.datetime(2026, 8, 20, 9, 0))
        )
        self.assertEqual(post.calls[0]["json"]["bill"]["expireDt"], "2026-08-20")


@override_settings(**CONFIGURED)
class ResponseHandlingTests(SimpleTestCase):
    """성공 판정과 재시도 분류 — 여기서 틀리면 조용히 어긋난다."""

    def test_v2_reads_msg_not_message(self):
        # V1 의 `message` 를 읽으면 거절 사유가 늘 비어 나간다.
        post = recorder(FakeResponse({"code": "VALIDATION_002", "msg": "해시 불일치"}))
        with self.assertRaises(PermanentPaymentError) as caught:
            PayssamAdapter(http_post=post).send_bill(bill_request())
        self.assertIn("해시 불일치", str(caught.exception))

    def test_permanent_vendor_codes_do_not_retry(self):
        for code in ["PARTNER_001", "VALIDATION_002", "BILL_001", "POINT_001"]:
            with self.subTest(code=code):
                post = recorder(FakeResponse({"code": code, "msg": "거절"}))
                with self.assertRaises(PermanentPaymentError):
                    PayssamAdapter(http_post=post).send_bill(bill_request())

    def test_transient_vendor_codes_are_retryable(self):
        for code in ["PAYMENT_001", "PAYMENT_002", "BILL_006", "MAINTAINED_METHOD", "ERROR"]:
            with self.subTest(code=code):
                post = recorder(FakeResponse({"code": code, "msg": "일시 오류"}))
                with self.assertRaises(TemporaryPaymentError):
                    PayssamAdapter(http_post=post).send_bill(bill_request())

    def test_unknown_vendor_code_is_permanent(self):
        # 모르는 코드를 재시도로 두면 거절당한 청구가 계속 다시 나간다.
        post = recorder(FakeResponse({"code": "듣도보도못한코드", "msg": "?"}))
        with self.assertRaises(PermanentPaymentError):
            PayssamAdapter(http_post=post).send_bill(bill_request())

    def test_server_error_is_retryable(self):
        post = recorder(FakeResponse({"code": "ERROR"}, status_code=500))
        with self.assertRaises(TemporaryPaymentError):
            PayssamAdapter(http_post=post).send_bill(bill_request())

    def test_client_error_is_permanent(self):
        post = recorder(FakeResponse({"code": "VALIDATION_001"}, status_code=400))
        with self.assertRaises(PermanentPaymentError):
            PayssamAdapter(http_post=post).send_bill(bill_request())

    def test_network_failure_is_retryable(self):
        post = recorder(error=RequestException("timeout"))
        with self.assertRaises(TemporaryPaymentError):
            PayssamAdapter(http_post=post).send_bill(bill_request())

    def test_non_json_response_is_retryable(self):
        # 점검 페이지·프록시 오류가 HTML 로 온다 — 나중에 다시 걸면 된다.
        post = recorder(FakeResponse(None))
        with self.assertRaises(TemporaryPaymentError):
            PayssamAdapter(http_post=post).send_bill(bill_request())

    def test_request_carries_a_timeout(self):
        # 없으면 워커가 업체 응답을 무한정 기다린다.
        post = recorder(ok({"shortUrl": "https://pay.ssam/abc"}))
        PayssamAdapter(http_post=post).send_bill(bill_request())
        self.assertTrue(post.calls[0]["timeout"])


@override_settings(**CONFIGURED)
class ReadBillTests(SimpleTestCase):
    def test_posts_to_read_endpoint(self):
        post = recorder(ok({"apprState": "W"}))
        PayssamAdapter(http_post=post).read_bill("1024")
        self.assertEqual(post.calls[0]["url"], "https://sandbox.example/partner/bill/read")

    def test_vendor_states_translate_to_neutral_values(self):
        # F/W/C/D 는 어댑터 안에서 끝난다 — 앱 레이어로 새면 PG 교체 때 안 맞는다.
        cases = {
            "W": BillState.PENDING,
            "F": BillState.PAID,
            "C": BillState.CANCELLED,
            "D": BillState.VOIDED,
        }
        for vendor, neutral in cases.items():
            with self.subTest(vendor=vendor):
                post = recorder(ok({"apprState": vendor, "apprPrice": "45000"}))
                receipt = PayssamAdapter(http_post=post).read_bill("1024")
                self.assertEqual(receipt.state, neutral)

    def test_unknown_vendor_state_is_permanent_error(self):
        # 모르는 상태를 대기로 넘기면 미결제로 오해해 재청구가 나간다.
        post = recorder(ok({"apprState": "Z"}))
        with self.assertRaises(PermanentPaymentError):
            PayssamAdapter(http_post=post).read_bill("1024")

    def test_approval_number_lands_in_the_neutral_external_ref(self):
        post = recorder(
            ok({"apprState": "F", "apprNum": "APPR-77", "apprPrice": "45000"})
        )
        receipt = PayssamAdapter(http_post=post).read_bill("1024")
        self.assertEqual(receipt.external_ref, "APPR-77")
        self.assertEqual(receipt.amount, 45000)

    def test_approval_datetime_is_parsed_as_seoul_time(self):
        post = recorder(
            ok({"apprState": "F", "apprDt": "20260805143000", "apprPrice": "45000"})
        )
        receipt = PayssamAdapter(http_post=post).read_bill("1024")
        self.assertIsNotNone(receipt.paid_at)
        self.assertEqual(receipt.paid_at.year, 2026)
        self.assertEqual(receipt.paid_at.hour, 14)
        self.assertIsNotNone(receipt.paid_at.tzinfo)

    def test_unpaid_bill_has_no_approval_values(self):
        post = recorder(ok({"apprState": "W", "apprPrice": "45000"}))
        receipt = PayssamAdapter(http_post=post).read_bill("1024")
        self.assertIsNone(receipt.external_ref)
        self.assertIsNone(receipt.paid_at)


@override_settings(**CONFIGURED)
class CancelAndDestroyTests(SimpleTestCase):
    def test_cancel_posts_to_cancel_endpoint_with_reason(self):
        post = recorder(ok({"apprNum": "CANCEL-1", "apprOriginNum": "APPR-77"}))
        PayssamAdapter(http_post=post).cancel_bill("1024", amount=45000, reason="환불")
        call = post.calls[0]
        self.assertEqual(call["url"], "https://sandbox.example/partner/bill/cancel")
        self.assertEqual(call["json"]["bill"]["cancelReason"], "환불")
        self.assertEqual(call["json"]["bill"]["price"], "45000")

    def test_cancel_returns_cancelled_state(self):
        post = recorder(ok({"apprNum": "CANCEL-1"}))
        receipt = PayssamAdapter(http_post=post).cancel_bill(
            "1024", amount=45000, reason="환불"
        )
        self.assertEqual(receipt.state, BillState.CANCELLED)

    def test_cancel_reason_is_clipped_to_the_vendor_limit(self):
        # cancelReason 은 20자 한도다. 넘겨 보내면 거절된다.
        post = recorder(ok({"apprNum": "CANCEL-1"}))
        PayssamAdapter(http_post=post).cancel_bill("1024", amount=45000, reason="가" * 40)
        self.assertEqual(len(post.calls[0]["json"]["bill"]["cancelReason"]), 20)

    def test_destroy_posts_to_destroy_endpoint(self):
        post = recorder(ok({"billId": "1024"}))
        PayssamAdapter(http_post=post).destroy_bill("1024", amount=45000)
        self.assertEqual(post.calls[0]["url"], "https://sandbox.example/partner/bill/destroy")

    def test_destroy_sends_the_two_part_hash(self):
        # 파기는 phone 을 싣지 않는다 — {billId},{price} 형식이다.
        post = recorder(ok({"billId": "1024"}))
        PayssamAdapter(http_post=post).destroy_bill("1024", amount=45000)
        expected = hashlib.sha256(b"1024,45000").hexdigest()
        self.assertEqual(post.calls[0]["json"]["bill"]["hash"], expected)


class ConfigurationTests(SimpleTestCase):
    """자격증명이 비면 닫힌다 — 안전 기본값(key_considerations §5).

    돈이 오가는 경로라 "미설정 = 조용한 성공"이 특히 위험하다.
    """

    @override_settings(**{**CONFIGURED, "PAYSSAM_API_KEY": ""})
    def test_missing_api_key_is_permanent_error(self):
        with self.assertRaises(PermanentPaymentError):
            PayssamAdapter(http_post=recorder()).send_bill(bill_request())

    @override_settings(**{**CONFIGURED, "PAYSSAM_MERCHANT_ID": ""})
    def test_missing_merchant_is_permanent_error(self):
        with self.assertRaises(PermanentPaymentError):
            PayssamAdapter(http_post=recorder()).send_bill(bill_request())

    @override_settings(**{**CONFIGURED, "PAYSSAM_API_BASE_URL": ""})
    def test_missing_base_url_is_permanent_error(self):
        with self.assertRaises(PermanentPaymentError):
            PayssamAdapter(http_post=recorder()).send_bill(bill_request())

"""결제 제공자 어댑터 계약 테스트 — 업체 교체 가능성이 핵심 (PRD 6-5, key_considerations §4).

여기서 지키는 것은 하나다: **결제선생 → PG 교체가 설정 한 줄이고 스키마는 안
움직인다.** 그래서 테스트도 "어떤 업체가 붙었나"가 아니라 "설정을 바꾸면 그쪽이
불리나"를 본다(notifications `test_channels.py` 선례와 같은 축).
"""
import datetime

from django.test import SimpleTestCase, override_settings

from .provider import (
    Balance,
    Bill,
    BillRequest,
    BillState,
    FakePaymentAdapter,
    PaymentAdapter,
    PaymentError,
    PermanentPaymentError,
    Receipt,
    TemporaryPaymentError,
    get_adapter,
)

FAKE = "apps.payments.provider.FakePaymentAdapter"
RECORDING = "apps.payments.test_provider.RecordingAdapter"


class RecordingAdapter(PaymentAdapter):
    """설정만 바꿔 끼우는 다른 업체(PG) 자리 — 교체 가능성 증인."""

    sent: list = []

    def send_bill(self, request):
        RecordingAdapter.sent.append(request)
        return Bill(bill_ref=request.bill_ref, pay_url="https://pg.example/pay/1")

    def read_bill(self, bill_ref):
        return Receipt(bill_ref=bill_ref, state=BillState.PAID, amount=1000)

    def cancel_bill(self, bill_ref, *, amount, reason):
        return Receipt(bill_ref=bill_ref, state=BillState.CANCELLED, amount=amount)

    def destroy_bill(self, bill_ref, *, amount):
        return None


def bill_request(**kwargs):
    kwargs.setdefault("bill_ref", "1")
    kwargs.setdefault("amount", 45000)
    kwargs.setdefault("customer_name", "김하늘")
    kwargs.setdefault("phone", "01012345678")
    kwargs.setdefault("product_name", "로직엔제 교재 Vol.1")
    kwargs.setdefault("callback_url", "https://lms.example/api/payments/callback")
    return BillRequest(**kwargs)


class BillRequestTests(SimpleTestCase):
    def test_request_carries_no_orm_object(self):
        # 어댑터는 ORM 을 모른다 — 업체 코드가 우리 모델을 붙들면 교체가 어려워지고
        # 어댑터 테스트에 DB 가 필요해진다(channels·conferencing 선례).
        request = bill_request()
        self.assertIsInstance(request.bill_ref, str)
        self.assertIsInstance(request.amount, int)
        for value in (request.customer_name, request.phone, request.product_name):
            self.assertIsInstance(value, str)

    def test_request_is_frozen(self):
        # 어댑터가 요청을 고쳐 쓰면 호출측이 보낸 것과 나간 것이 갈린다.
        with self.assertRaises(Exception):
            bill_request().amount = 1


class BillStateTests(SimpleTestCase):
    """중립 상태값 — 업체 코드(F/W/C/D)는 어댑터 안에서 끝난다."""

    def test_state_set_is_vendor_neutral(self):
        # 결제선생의 F/W/C/D 가 그대로 새어 나오면 PG 로 바꿀 때 값이 안 맞는다.
        self.assertEqual(
            set(BillState.values), {"대기", "완료", "취소", "파기"}
        )

    def test_no_vendor_codes_leak_into_state_values(self):
        self.assertFalse({"F", "W", "C", "D"} & set(BillState.values))


class PaymentRegistryTests(SimpleTestCase):
    def setUp(self):
        FakePaymentAdapter.sent.clear()
        RecordingAdapter.sent.clear()

    @override_settings(PAYMENT_PROVIDER_BACKEND=FAKE)
    def test_adapter_resolved_from_settings(self):
        self.assertIsInstance(get_adapter(), FakePaymentAdapter)

    @override_settings(PAYMENT_PROVIDER_BACKEND=RECORDING)
    def test_provider_swaps_by_settings_alone(self):
        # 업체 교체(결제선생 → PG) = 설정 한 줄. 스키마도 값집합도 그대로다.
        get_adapter().send_bill(bill_request())
        self.assertEqual(len(RecordingAdapter.sent), 1)
        self.assertEqual(FakePaymentAdapter.sent, [])

    @override_settings(PAYMENT_PROVIDER_BACKEND="")
    def test_unconfigured_provider_is_permanent_error(self):
        # 안전 기본값은 닫힘(key_considerations §5). 돈이 오가는 경로라
        # "미설정 = 조용한 성공" 이 특히 위험하다 — 청구서가 안 나갔는데
        # 주문만 청구됨으로 넘어가면 배부가 무료로 나간다.
        with self.assertRaises(PermanentPaymentError):
            get_adapter()

    @override_settings(PAYMENT_PROVIDER_BACKEND="apps.payments.provider.없는어댑터")
    def test_broken_backend_path_is_permanent_error(self):
        with self.assertRaises(PermanentPaymentError):
            get_adapter()

    @override_settings(PAYMENT_PROVIDER_BACKEND=FAKE)
    def test_adapter_is_not_cached_between_calls(self):
        # 캐시를 두면 설정 교체(운영 롤아웃·테스트 override)가 조용히 옛
        # 구현체를 계속 쓴다(channels·conferencing 이 같은 이유로 캐시 안 함).
        self.assertIsNot(get_adapter(), get_adapter())


class PaymentErrorTests(SimpleTestCase):
    def test_error_kinds_split_retryable_from_final(self):
        # 재시도 여부는 예외 종류가 말한다 — 업체 응답 문자열을 호출측이
        # 파싱해 갈리면 업체마다 규칙이 달라져 재시도 정책이 무너진다.
        self.assertTrue(issubclass(TemporaryPaymentError, PaymentError))
        self.assertTrue(issubclass(PermanentPaymentError, PaymentError))
        self.assertFalse(issubclass(TemporaryPaymentError, PermanentPaymentError))
        self.assertFalse(issubclass(PermanentPaymentError, TemporaryPaymentError))


class FakePaymentAdapterTests(SimpleTestCase):
    """로컬·테스트용 — 실제로 청구서를 보내지 않는다."""

    def setUp(self):
        # 보관함이 클래스 레벨이라 테스트 사이에 남는다 — 안 비우면 앞 테스트가
        # 만든 청구서를 뒤 테스트가 주워 본다(channels outbox 와 같은 처리).
        FakePaymentAdapter.sent.clear()
        FakePaymentAdapter._bills.clear()

    def test_fake_records_what_it_was_asked_to_send(self):
        request = bill_request()
        bill = FakePaymentAdapter().send_bill(request)
        self.assertEqual(FakePaymentAdapter.sent, [request])
        self.assertEqual(bill.bill_ref, request.bill_ref)

    def test_fake_returns_a_pay_url_so_the_embed_has_something_to_open(self):
        # PRD 3.2.5 임베드는 결제 URL 이 있어야 성립한다. 빈 URL 을 돌려주면
        # 화면이 조용히 빈 iframe 을 띄운다.
        self.assertTrue(FakePaymentAdapter().send_bill(bill_request()).pay_url)

    def test_fake_bill_starts_unpaid(self):
        FakePaymentAdapter().send_bill(bill_request(bill_ref="7"))
        self.assertEqual(FakePaymentAdapter().read_bill("7").state, BillState.PENDING)

    def test_unknown_bill_read_is_permanent_error(self):
        # 없는 청구서를 조회하면 재시도해도 같다.
        with self.assertRaises(PermanentPaymentError):
            FakePaymentAdapter().read_bill("없는번호")


class ReceiptTests(SimpleTestCase):
    def test_receipt_carries_neutral_external_reference(self):
        # 업체 참조는 중립 컬럼 하나(external_ref)로만 들어온다 — 모델에
        # 업체 종속 컬럼을 만들지 않기 위한 자리(Payment 모델 계약).
        receipt = Receipt(
            bill_ref="1",
            state=BillState.PAID,
            amount=45000,
            external_ref="APPR-0001",
            paid_at=datetime.datetime(2026, 8, 5, 12, 0),
        )
        self.assertEqual(receipt.external_ref, "APPR-0001")
        self.assertEqual(receipt.state, BillState.PAID)

    def test_receipt_external_reference_is_optional(self):
        # 미결제 건은 승인번호가 아직 없다 — 조회는 성립해야 한다.
        receipt = Receipt(bill_ref="1", state=BillState.PENDING, amount=45000)
        self.assertIsNone(receipt.external_ref)
        self.assertIsNone(receipt.paid_at)


class BalanceContractTests(SimpleTestCase):
    """선불 잔액 조회 — 자동충전을 안 켜기로 해서(2026-08-11) 사람이 봐야 한다.

    잔액은 업체 고유 개념처럼 보이지만 "선불 잔액"은 어느 제공자에게나 있을 수
    있어 중립 계약에 둔다. **다만 필수는 아니다** — 잔액 개념이 없는 PG 로
    바꿔도 구현체가 안 깨지도록 기본 구현은 None 을 돌려준다.
    """

    def test_balance_is_optional_for_a_provider(self):
        class Minimal(RecordingAdapter):
            pass

        self.assertIsNone(Minimal().read_balance())

    def test_balance_carries_amount_and_a_charge_link(self):
        # 충전 링크가 같이 와야 관리자가 잔액을 보고 **그 자리에서** 채운다.
        balance = Balance(amount=12000, charge_url="https://pay.example/charge")
        self.assertEqual(balance.amount, 12000)
        self.assertEqual(balance.charge_url, "https://pay.example/charge")


class SettingsWiringTests(SimpleTestCase):
    """어느 환경이 어떤 구현체를 쓰는지 — 여기서 틀리면 청구가 통째로 어긋난다.

    `NOTIFICATION_CHANNEL_BACKENDS` 와 같은 축이다(notifications
    `test_channels.SettingsWiringTests` 선례). 결제 쪽이 더 위험하다:
    Fake 가 운영에 남으면 결제 내역에는 청구 성공만 쌓이고 학부모는 아무
    청구서도 못 받는다.
    """

    def test_base_leaves_the_provider_closed(self):
        # 안전 기본값은 닫힘 — 새 환경이 아무것도 안 물리면 청구가 실패한다.
        from config.settings import base

        self.assertEqual(base.PAYMENT_PROVIDER_BACKEND, "")

    def test_prod_wires_the_real_vendor_not_the_fake(self):
        # 운영은 오브젝트 스토리지 없이는 부팅을 거부하므로 버킷을 채우고 읽는다
        # (`notifications.test_channels` 의 같은 테스트와 같은 처리). 그냥 import 하면
        # 앞선 테스트가 환경을 남겨 준 실행에서만 통과한다.
        import importlib
        import os
        from unittest import mock

        with mock.patch.dict(os.environ, {"AWS_STORAGE_BUCKET_NAME": "test-bucket"}):
            prod = importlib.reload(importlib.import_module("config.settings.prod"))

        self.assertIn("payssam", prod.PAYMENT_PROVIDER_BACKEND.lower())
        self.assertNotIn("Fake", prod.PAYMENT_PROVIDER_BACKEND)

    def test_dev_wires_the_fake_so_bills_do_not_leave_the_machine(self):
        # 시드 연락처는 진짜 번호일 수 있다 — 로컬에서 구매를 눌러 보는 것만으로
        # 모르는 사람에게 카카오톡 청구서가 가면 안 된다.
        from config.settings import dev

        self.assertIn("Fake", dev.PAYMENT_PROVIDER_BACKEND)

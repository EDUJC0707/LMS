"""결제 승인 콜백 테스트 — POST /api/payments/callback (PRD 3.1.5 동기화).

**이 엔드포인트는 인증이 없다.** 업체 문서에 콜백 서명·검증 수단이 없고
(2026-08-05 조사), 그래서 **본문을 믿으면 안 된다** — 아무나 `billId` 를 찍어
POST 하면 결제가 완료로 넘어가고 교재가 공짜로 배부된다. 방어는 하나다:
콜백은 **"가서 확인해 보라"는 신호로만** 쓰고, 실제 상태는 업체에게 되물어
(`read_bill`) 확정한다.

업체 계약: 수신 성공은 `{"code": "0000"}` 응답이다.

**중복 전달 보장도 문서에 없다.** 같은 승인이 두 번 와도 결과가 같아야 한다
(멱등) — 아니면 Payment 행이 두 개 쌓여 대사가 어긋난다.
"""
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import Student, User

from .models import Order, Payment, Product
from .provider import BillState, PaymentAdapter, Receipt, TemporaryPaymentError

URL = "/api/payments/callback"
PAID = "apps.payments.test_callback_api.PaidAdapter"
UNPAID = "apps.payments.test_callback_api.UnpaidAdapter"
FLAKY = "apps.payments.test_callback_api.FlakyAdapter"


class _BaseAdapter(PaymentAdapter):
    provider_value = "결제선생"
    reads: list = []

    def send_bill(self, request):
        raise NotImplementedError

    def cancel_bill(self, bill_ref, *, amount, reason):
        raise NotImplementedError

    def destroy_bill(self, bill_ref, *, amount):
        raise NotImplementedError


class PaidAdapter(_BaseAdapter):
    def read_bill(self, bill_ref):
        _BaseAdapter.reads.append(bill_ref)
        return Receipt(
            bill_ref=bill_ref,
            state=BillState.PAID,
            amount=45000,
            external_ref="APPR-77",
            paid_at=timezone.now(),
        )


class UnpaidAdapter(_BaseAdapter):
    def read_bill(self, bill_ref):
        _BaseAdapter.reads.append(bill_ref)
        return Receipt(bill_ref=bill_ref, state=BillState.PENDING, amount=45000)


class FlakyAdapter(_BaseAdapter):
    def read_bill(self, bill_ref):
        raise TemporaryPaymentError("점검 중입니다.")


@override_settings(PAYMENT_PROVIDER_BACKEND=PAID)
class CallbackTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.product = Product.objects.create(name="로직엔제 교재 Vol.1", price=45000)
        cls.student = Student.objects.create(
            user=User.objects.create_user(
                login_id="cb-stu", password="pw-Secret-77!", name="김하늘",
                role=User.Role.STUDENT,
            ),
            matching_key="3_0001",
        )

    def setUp(self):
        _BaseAdapter.reads.clear()
        self.order = Order.objects.create(
            student=self.student, product=self.product, amount=45000, is_billed=True
        )
        self.payment = Payment.objects.create(
            order=self.order,
            provider=Payment.Provider.PAYSSAM,
            status=Payment.Status.PENDING,
            amount=45000,
        )

    def notify(self, bill_id=None, **extra):
        payload = {"billId": str(bill_id or self.order.order_id), **extra}
        return self.client.post(URL, payload, content_type="application/json")

    # -- 업체 계약 ----------------------------------------------------------

    def test_acknowledges_with_the_code_the_vendor_expects(self):
        response = self.notify()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["code"], "0000")

    def test_no_login_required(self):
        # 업체 서버가 부른다 — 세션이 없다.
        self.assertEqual(self.notify().status_code, 200)

    # -- 본문을 믿지 않는다 --------------------------------------------------

    def test_payment_state_comes_from_the_vendor_not_the_request_body(self):
        # 본문이 뭐라고 하든 우리는 업체에게 되묻는다.
        self.notify(apprState="F", apprPrice="999999")
        self.assertEqual(_BaseAdapter.reads, [str(self.order.order_id)])
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.amount, 45000)  # 본문의 999999 가 아니다

    @override_settings(PAYMENT_PROVIDER_BACKEND=UNPAID)
    def test_a_forged_callback_cannot_mark_an_unpaid_order_paid(self):
        # **이 엔드포인트의 존재 이유가 이 테스트다.** 인증이 없으므로 아무나
        # 부를 수 있고, 업체가 미결제라고 답하면 아무것도 바뀌면 안 된다.
        response = self.notify(apprState="F")
        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.payment.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.UNPAID)
        self.assertEqual(self.payment.status, Payment.Status.PENDING)
        self.assertIsNone(self.order.paid_at)

    # -- 정상 승인 ----------------------------------------------------------

    def test_confirmed_payment_moves_order_and_transaction(self):
        self.notify()
        self.order.refresh_from_db()
        self.payment.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PAID)
        self.assertIsNotNone(self.order.paid_at)
        self.assertEqual(self.payment.status, Payment.Status.COMPLETED)
        self.assertIsNotNone(self.payment.paid_at)

    def test_vendor_approval_number_lands_in_the_neutral_column(self):
        self.notify()
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.external_ref, "APPR-77")

    def test_sync_time_is_recorded(self):
        # synced_at = 동기화 시각(Payment 모델 계약). 언제 맞춰 본 값인지 없으면
        # 대사에서 "이 행이 최신인가"를 못 판단한다.
        self.notify()
        self.payment.refresh_from_db()
        self.assertIsNotNone(self.payment.synced_at)

    # -- 멱등 ---------------------------------------------------------------

    def test_duplicate_delivery_does_not_create_a_second_transaction(self):
        # 업체 문서에 중복 전달 보장이 없다 — 두 번 와도 결과가 같아야 한다.
        self.notify()
        self.notify()
        self.assertEqual(self.order.payments.count(), 1)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PAID)

    def test_delivered_order_is_not_dragged_back_to_paid(self):
        # 이미 배부까지 끝난 주문에 승인 콜백이 늦게 도착해도 상태가 뒤로
        # 가면 안 된다 — 배부완료는 결제완료 다음 단계다.
        self.order.status = Order.Status.DELIVERED
        self.order.delivered_at = timezone.now()
        self.order.save(update_fields=["status", "delivered_at"])
        self.notify()
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.DELIVERED)

    # -- 잘못된 입력 --------------------------------------------------------

    def test_unknown_bill_is_not_silently_acknowledged(self):
        # 0000 으로 삼켜 버리면 업체와 우리 장부가 어긋난 사실이 사라진다.
        response = self.notify(bill_id=999999)
        self.assertNotEqual(response.json()["code"], "0000")

    def test_missing_bill_id_is_rejected(self):
        response = self.client.post(URL, {}, content_type="application/json")
        self.assertNotEqual(response.json()["code"], "0000")

    @override_settings(PAYMENT_PROVIDER_BACKEND=FLAKY)
    def test_vendor_unreachable_is_not_acknowledged_so_it_can_be_redelivered(self):
        response = self.notify()
        self.assertNotEqual(response.json()["code"], "0000")
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.UNPAID)

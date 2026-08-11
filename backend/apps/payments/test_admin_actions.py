"""관리자 결제 조작 테스트 — 취소·환불과 배부 처리 (PRD 3.1.5).

**두 동작의 무게가 다르다.**
- 배부완료는 일상 운영이다(`결제확인` 기능 키).
- **취소·환불은 돈이 되돌아가는 파괴적 조작**이라 `key_considerations §2` 가
  대표 전용 후보로 꼽아 둔 것이고, §5("파괴적 작업은 자동화하지 않고 관리자
  수동 + 이력")에 해당한다. 그래서 **역할 게이트(대표)**로 잠근다 —
  관리자가 `결제확인` 을 들고 있어도 환불은 못 낸다.

**업체에 무엇을 부르는지가 상태마다 다르다**(2026-08-11 문서 확인):
- 결제완료 → `/bill/cancel`(승인취소). 미결제 건에는 못 쓴다
- 미결제 + 청구서 발송됨 → `/bill/destroy`(파기). 승인 전에만 된다
- 청구서를 아직 안 보냈으면 → 업체에 아무것도 없다. 우리 행만 접는다
"""
from django.test import TestCase, override_settings

from apps.accounts.features import FeatureKey
from apps.accounts.models import StaffFeatureGrant, Student, User

from .models import Order, Payment, Product
from .provider import Bill, BillState, PaymentAdapter, Receipt

PASSWORD = "pw-Secret-77!"
RECORDING = "apps.payments.test_admin_actions.RecordingAdapter"


class RecordingAdapter(PaymentAdapter):
    provider_value = "결제선생"
    calls: list = []

    def send_bill(self, request) -> Bill:
        return Bill(bill_ref=request.bill_ref, pay_url="https://pay.test/1")

    def read_bill(self, bill_ref):
        return Receipt(bill_ref=bill_ref, state=BillState.PAID, amount=45000)

    def cancel_bill(self, bill_ref, *, amount, reason):
        RecordingAdapter.calls.append(("cancel", bill_ref, amount, reason))
        return Receipt(bill_ref=bill_ref, state=BillState.CANCELLED, amount=amount)

    def destroy_bill(self, bill_ref, *, amount):
        RecordingAdapter.calls.append(("destroy", bill_ref, amount))
        return None


def make_user(login_id, role, name="사용자"):
    return User.objects.create_user(
        login_id=login_id, password=PASSWORD, name=name, role=role
    )


@override_settings(PAYMENT_PROVIDER_BACKEND=RECORDING)
class AdminActionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user("aa-own", User.Role.OWNER, name="대표")
        cls.admin = make_user("aa-adm", User.Role.ADMIN, name="관리자")
        cls.product = Product.objects.create(name="로직엔제 교재 Vol.1", price=45000)
        cls.student = Student.objects.create(
            user=make_user("aa-stu", User.Role.STUDENT, name="김하늘"),
            matching_key="3_0001",
        )

    def setUp(self):
        RecordingAdapter.calls.clear()

    def make_order(self, status=Order.Status.UNPAID, is_billed=True, with_payment=False):
        order = Order.objects.create(
            student=self.student,
            product=self.product,
            amount=45000,
            status=status,
            is_billed=is_billed,
        )
        if with_payment:
            Payment.objects.create(
                order=order,
                provider=Payment.Provider.PAYSSAM,
                status=Payment.Status.COMPLETED,
                amount=45000,
                external_ref="APPR-77",
            )
        return order

    def cancel_url(self, order):
        return f"/api/admin/payments/{order.order_id}/cancel"

    def deliver_url(self, order):
        return f"/api/admin/payments/{order.order_id}/deliver"

    # -- 취소 게이트: 대표 전용 -------------------------------------------

    def test_admin_cannot_refund(self):
        # 돈이 되돌아가는 조작이라 기능 키로 열지 않는다(key_considerations §2).
        order = self.make_order(Order.Status.PAID, with_payment=True)
        self.client.force_login(self.admin)
        response = self.client.post(self.cancel_url(order), {"reason": "환불"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(RecordingAdapter.calls, [])

    def test_admin_with_the_payment_feature_still_cannot_refund(self):
        # `결제확인` 을 들고 있어도 안 된다 — 역할 게이트라서 delta 로 안 열린다.
        StaffFeatureGrant.objects.create(
            user=self.admin, feature_key=FeatureKey.PAYMENT_CHECK, is_granted=True
        )
        order = self.make_order(Order.Status.PAID, with_payment=True)
        self.client.force_login(self.admin)
        self.assertEqual(
            self.client.post(self.cancel_url(order), {"reason": "환불"}).status_code, 403
        )

    def test_owner_can_refund(self):
        order = self.make_order(Order.Status.PAID, with_payment=True)
        self.client.force_login(self.owner)
        self.assertEqual(
            self.client.post(self.cancel_url(order), {"reason": "환불"}).status_code, 200
        )

    # -- 취소: 상태마다 업체 호출이 다르다 ---------------------------------

    def test_paid_order_is_cancelled_at_the_vendor(self):
        order = self.make_order(Order.Status.PAID, with_payment=True)
        self.client.force_login(self.owner)
        self.client.post(self.cancel_url(order), {"reason": "학부모 요청"})
        self.assertEqual(RecordingAdapter.calls[0][0], "cancel")
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CANCELLED)
        self.assertEqual(order.payments.first().status, Payment.Status.CANCELLED)

    def test_unpaid_but_billed_order_is_destroyed_not_cancelled(self):
        # 승인 전이라 /bill/cancel 이 안 먹는다 — 파기가 맞는 호출이다.
        order = self.make_order(Order.Status.UNPAID, is_billed=True)
        self.client.force_login(self.owner)
        self.client.post(self.cancel_url(order), {"reason": "오청구"})
        self.assertEqual(RecordingAdapter.calls[0][0], "destroy")
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CANCELLED)

    def test_unbilled_order_touches_the_vendor_at_all(self):
        # 청구서를 안 보냈으면 업체에 아무것도 없다. 부르면 BILL_003 이 난다.
        order = self.make_order(Order.Status.UNPAID, is_billed=False)
        self.client.force_login(self.owner)
        self.client.post(self.cancel_url(order), {"reason": "오등록"})
        self.assertEqual(RecordingAdapter.calls, [])
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CANCELLED)

    def test_cancelling_twice_is_rejected(self):
        order = self.make_order(Order.Status.CANCELLED)
        self.client.force_login(self.owner)
        self.assertEqual(
            self.client.post(self.cancel_url(order), {"reason": "재취소"}).status_code, 400
        )
        self.assertEqual(RecordingAdapter.calls, [])

    def test_reason_is_required(self):
        # 이력이 남아야 하는 조작이다(§5) — 사유 없는 환불은 받지 않는다.
        order = self.make_order(Order.Status.PAID, with_payment=True)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.post(self.cancel_url(order), {}).status_code, 400)
        self.assertEqual(RecordingAdapter.calls, [])

    def test_cancelled_order_frees_the_slot_for_a_new_bill(self):
        # 부분 UQ 는 취소 건을 제외한다 — 취소 후 재청구가 성립해야 한다.
        order = self.make_order(Order.Status.PAID, with_payment=True)
        self.client.force_login(self.owner)
        self.client.post(self.cancel_url(order), {"reason": "환불"})
        Order.objects.create(student=self.student, product=self.product, amount=45000)

    # -- 배부완료 ----------------------------------------------------------

    def test_delivering_needs_the_payment_feature(self):
        order = self.make_order(Order.Status.PAID, with_payment=True)
        assistant = make_user("aa-ast", User.Role.ASSISTANT)
        self.client.force_login(assistant)
        self.assertEqual(self.client.post(self.deliver_url(order)).status_code, 403)

    def test_admin_can_mark_delivered(self):
        # 배부는 일상 운영이라 기능 키로 연다(취소와 달리 대표 전용이 아니다).
        order = self.make_order(Order.Status.PAID, with_payment=True)
        self.client.force_login(self.admin)
        response = self.client.post(self.deliver_url(order))
        self.assertEqual(response.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.DELIVERED)
        self.assertIsNotNone(order.delivered_at)

    def test_unpaid_order_cannot_be_delivered(self):
        # 결제되지 않은 교재를 배부완료로 넘기면 무료로 나간 것이 장부에서 사라진다.
        order = self.make_order(Order.Status.UNPAID)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(self.deliver_url(order)).status_code, 400)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.UNPAID)

    def test_delivering_twice_keeps_the_first_time(self):
        order = self.make_order(Order.Status.PAID, with_payment=True)
        self.client.force_login(self.admin)
        self.client.post(self.deliver_url(order))
        order.refresh_from_db()
        first = order.delivered_at
        self.client.post(self.deliver_url(order))
        order.refresh_from_db()
        self.assertEqual(order.delivered_at, first)

    def test_unknown_order_is_404(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post("/api/admin/payments/999999/deliver").status_code, 404)

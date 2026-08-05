"""교재 청구 개시 API 테스트 — 양측 결제 + 중복 차단 (PRD 3.1.5·3.2.5).

PRD 요구 두 가지가 여기서 만난다:
- *"학생 또는 학부모가 교재 구매를 희망할 때 **버튼 클릭만으로 청구가 시작**"*
- *"동일 학생·동일 교재에 대해 청구/결제가 한 번 성립하면 다른 경로의 청구서
  발송을 자동 차단"*

**중복 차단이 이 파일의 핵심이다.** 청구서는 한 건마다 쌤포인트를 태우고,
학부모에게 같은 청구가 두 번 가면 as-is 의 불만("외부 프로그램 다수로
학부모가 어려워함")이 그대로 재현된다. 방어는 두 겹이다 — 앱 레이어의
`is_billed` 선재 검사와 DB 의 부분 UQ(활성 청구 1건).
"""
from django.test import TestCase, override_settings

from apps.accounts.models import Parent, ParentStudent, Student, User

from .models import Order, Payment, Product
from .provider import (
    Bill,
    BillRequest,
    PaymentAdapter,
    PermanentPaymentError,
    TemporaryPaymentError,
)

PASSWORD = "pw-Secret-77!"
STUDENT_URL = "/api/student/payments/bill"
PARENT_URL = "/api/parent/payments/bill"
RECORDING = "apps.payments.test_billing_api.RecordingAdapter"
FAILING_PERMANENT = "apps.payments.test_billing_api.PermanentFailAdapter"
FAILING_TEMPORARY = "apps.payments.test_billing_api.TemporaryFailAdapter"


class RecordingAdapter(PaymentAdapter):
    provider_value = "결제선생"
    sent: list = []

    def send_bill(self, request: BillRequest) -> Bill:
        RecordingAdapter.sent.append(request)
        return Bill(bill_ref=request.bill_ref, pay_url=f"https://pay.test/{request.bill_ref}")

    def read_bill(self, bill_ref):
        raise NotImplementedError

    def cancel_bill(self, bill_ref, *, amount, reason):
        raise NotImplementedError

    def destroy_bill(self, bill_ref, *, amount):
        raise NotImplementedError


class PermanentFailAdapter(RecordingAdapter):
    def send_bill(self, request):
        raise PermanentPaymentError("포인트가 부족합니다.")


class TemporaryFailAdapter(RecordingAdapter):
    def send_bill(self, request):
        raise TemporaryPaymentError("점검 중입니다.")


def make_user(login_id, role, name="사용자", **extra):
    return User.objects.create_user(
        login_id=login_id, password=PASSWORD, name=name, role=role, **extra
    )


@override_settings(PAYMENT_PROVIDER_BACKEND=RECORDING)
class BillingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.product = Product.objects.create(name="로직엔제 교재 Vol.1", price=45000)
        cls.retired = Product.objects.create(name="폐기 교재", price=1000, is_active=False)

        cls.student_user = make_user(
            "bl-stu", User.Role.STUDENT, name="김하늘", phone="01012345678"
        )
        cls.student = Student.objects.create(user=cls.student_user, matching_key="3_0001")
        cls.other_student = Student.objects.create(
            user=make_user("bl-stu2", User.Role.STUDENT), matching_key="3_0002"
        )
        cls.parent_user = make_user("bl-par", User.Role.PARENT, name="학부모")
        cls.parent = Parent.objects.create(user=cls.parent_user, phone="01099998888")
        ParentStudent.objects.create(parent=cls.parent, student=cls.student)
        cls.staff = make_user("bl-adm", User.Role.ADMIN)

    def setUp(self):
        RecordingAdapter.sent.clear()

    def start(self, url=STUDENT_URL, **payload):
        payload.setdefault("product_id", self.product.product_id)
        return self.client.post(url, payload)

    # -- 게이트 -------------------------------------------------------------

    def test_anonymous_cannot_start_billing(self):
        self.assertEqual(self.start().status_code, 403)

    def test_staff_cannot_use_the_consumer_billing_route(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.start().status_code, 403)

    # -- 학생 개시 ----------------------------------------------------------

    def test_student_starts_billing_with_one_click(self):
        self.client.force_login(self.student_user)
        response = self.start()
        self.assertEqual(response.status_code, 201)
        body = response.json()
        order = Order.objects.get(student=self.student, product=self.product)
        self.assertEqual(body["order_id"], order.order_id)
        self.assertEqual(body["pay_url"], f"https://pay.test/{order.order_id}")

    def test_billing_marks_the_order_sent_and_records_the_transaction(self):
        self.client.force_login(self.student_user)
        self.start()
        order = Order.objects.get(student=self.student, product=self.product)
        self.assertTrue(order.is_billed)
        self.assertIsNotNone(order.billed_at)
        self.assertEqual(order.status, Order.Status.UNPAID)
        self.assertEqual(order.amount, 45000)
        self.assertEqual(order.initiated_by_user, self.student_user)
        payment = order.payments.get()
        self.assertEqual(payment.status, Payment.Status.PENDING)
        self.assertEqual(payment.provider, Payment.Provider.PAYSSAM)

    def test_bill_carries_the_student_phone_and_product_name(self):
        self.client.force_login(self.student_user)
        self.start()
        request = RecordingAdapter.sent[0]
        self.assertEqual(request.phone, "01012345678")
        self.assertEqual(request.product_name, "로직엔제 교재 Vol.1")
        self.assertEqual(request.amount, 45000)
        self.assertEqual(request.customer_name, "김하늘")

    def test_amount_is_snapshotted_at_order_time(self):
        # 교재 가격이 나중에 바뀌어도 이미 청구된 금액은 안 움직인다(Order 계약).
        self.client.force_login(self.student_user)
        self.start()
        self.product.price = 99000
        self.product.save(update_fields=["price"])
        order = Order.objects.get(student=self.student, product=self.product)
        self.assertEqual(order.amount, 45000)

    def test_inactive_product_cannot_be_billed(self):
        self.client.force_login(self.student_user)
        response = self.start(product_id=self.retired.product_id)
        self.assertEqual(response.status_code, 404)

    def test_unknown_product_is_404(self):
        self.client.force_login(self.student_user)
        self.assertEqual(self.start(product_id=999999).status_code, 404)

    # -- 중복 차단(sync) ----------------------------------------------------

    def test_second_click_does_not_send_a_second_bill(self):
        # 청구서 1건 = 쌤포인트 1건이고 학부모에게 두 번 간다.
        self.client.force_login(self.student_user)
        first = self.start().json()
        second = self.start()
        self.assertEqual(second.status_code, 200)  # 새로 만든 것이 아니다
        self.assertEqual(len(RecordingAdapter.sent), 1)
        self.assertEqual(second.json()["pay_url"], first["pay_url"])
        self.assertEqual(Order.objects.filter(student=self.student).count(), 1)

    def test_parent_click_after_student_click_does_not_resend(self):
        # **양측 sync** — 경로가 달라도 같은 학생·같은 교재면 한 번이다.
        self.client.force_login(self.student_user)
        self.start()
        self.client.force_login(self.parent_user)
        response = self.client.post(PARENT_URL, {"product_id": self.product.product_id})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(RecordingAdapter.sent), 1)

    def test_cancelled_order_can_be_billed_again(self):
        Order.objects.create(
            student=self.student,
            product=self.product,
            amount=45000,
            status=Order.Status.CANCELLED,
            is_billed=True,
        )
        self.client.force_login(self.student_user)
        response = self.start()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(RecordingAdapter.sent), 1)
        self.assertEqual(Order.objects.filter(student=self.student).count(), 2)

    # -- 학부모 개시 --------------------------------------------------------

    def test_parent_starts_billing_for_a_linked_child(self):
        self.client.force_login(self.parent_user)
        response = self.client.post(PARENT_URL, {"product_id": self.product.product_id})
        self.assertEqual(response.status_code, 201)
        order = Order.objects.get(student=self.student, product=self.product)
        self.assertEqual(order.initiated_by_user, self.parent_user)
        self.assertEqual(order.billed_to_parent, self.parent)

    def test_parent_bill_goes_to_the_parent_phone(self):
        # 청구서를 받는 것은 학부모다(billed_to_phone 스냅샷).
        self.client.force_login(self.parent_user)
        self.client.post(PARENT_URL, {"product_id": self.product.product_id})
        self.assertEqual(RecordingAdapter.sent[0].phone, "01099998888")
        order = Order.objects.get(student=self.student)
        self.assertEqual(order.billed_to_phone, "01099998888")

    def test_parent_cannot_bill_for_a_child_that_is_not_theirs(self):
        self.client.force_login(self.parent_user)
        response = self.client.post(
            PARENT_URL,
            {
                "product_id": self.product.product_id,
                "student_id": self.other_student.student_id,
            },
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(RecordingAdapter.sent, [])

    # -- 업체 실패 ----------------------------------------------------------

    @override_settings(PAYMENT_PROVIDER_BACKEND=FAILING_PERMANENT)
    def test_permanent_vendor_failure_leaves_nothing_marked_billed(self):
        # 청구서가 안 나갔는데 is_billed 가 서면 그 학생은 **영원히 재청구를
        # 못 받는다** — 중복 차단이 자기 자신을 막는다.
        self.client.force_login(self.student_user)
        response = self.start()
        self.assertEqual(response.status_code, 502)
        self.assertIn("포인트", response.json()["detail"])
        self.assertFalse(Order.objects.filter(student=self.student, is_billed=True).exists())

    @override_settings(PAYMENT_PROVIDER_BACKEND=FAILING_TEMPORARY)
    def test_temporary_vendor_failure_says_to_try_again(self):
        self.client.force_login(self.student_user)
        response = self.start()
        self.assertEqual(response.status_code, 503)
        self.assertFalse(Order.objects.filter(student=self.student, is_billed=True).exists())

    @override_settings(PAYMENT_PROVIDER_BACKEND="")
    def test_unconfigured_provider_does_not_pretend_to_succeed(self):
        self.client.force_login(self.student_user)
        self.assertEqual(self.start().status_code, 502)
        self.assertFalse(Order.objects.filter(student=self.student).exists())

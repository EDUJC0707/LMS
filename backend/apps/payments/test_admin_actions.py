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
from apps.accounts.models import Parent, StaffFeatureGrant, Student, User
from apps.curriculum.models import Class, Course, CourseEnrollment, Subject
from apps.notifications.models import Notification

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


@override_settings(PAYMENT_PROVIDER_BACKEND=RECORDING)
class CancelNotificationTests(TestCase):
    """취소하면 **우리가** 알린다 — 업체는 취소를 안 알려 준다(2026-08-11 실측).

    `/bill/cancel` 요청에는 `sendType`·`message` 같은 통지 항목이 아예 없다.
    결제선생은 **청구할 때만** 알림톡을 보낸다. 그래서 학부모 입장에서는 돈이
    조용히 돌아오거나(환불) 청구서가 조용히 사라진다(파기).

    **8-17 대기 중이다.** 알림톡 템플릿이 아직 승인 전이라 발송은
    "승인된 알림톡 템플릿 코드가 없습니다: 결제" 로 실패한다 — 행과 사유는
    남는다(조용한 성공 금지). 템플릿이 오면 이 자리는 안 고쳐도 된다.
    """

    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user("cn-own", User.Role.OWNER, name="대표")
        cls.product = Product.objects.create(name="로직엔제 교재 Vol.1", price=45000)
        cls.student = Student.objects.create(
            user=make_user("cn-stu", User.Role.STUDENT, name="김하늘"),
            matching_key="3_0001",
        )
        cls.parent = Parent.objects.create(
            user=make_user("cn-par", User.Role.PARENT, name="김학부"), phone="01099998888"
        )

    def setUp(self):
        RecordingAdapter.calls.clear()
        self.client.force_login(self.owner)

    def order(self, **kwargs):
        kwargs.setdefault("status", Order.Status.PAID)
        kwargs.setdefault("is_billed", True)
        order = Order.objects.create(
            student=self.student, product=self.product, amount=45000, **kwargs
        )
        Payment.objects.create(
            order=order,
            provider=Payment.Provider.PAYSSAM,
            status=Payment.Status.COMPLETED,
            amount=45000,
        )
        return order

    def cancel(self, order, reason="학부모 요청"):
        return self.client.post(
            f"/api/admin/payments/{order.order_id}/cancel", {"reason": reason}
        )

    def test_cancelling_a_paid_order_notifies(self):
        from apps.notifications.models import Notification

        self.cancel(self.order())
        notification = Notification.objects.get(type=Notification.Type.PAYMENT)
        self.assertEqual(notification.student, self.student)
        self.assertIn("환불", notification.body)

    def test_the_bill_recipient_is_the_one_told(self):
        # 청구서를 받은 것이 학부모면 취소도 학부모가 알아야 한다.
        from apps.notifications.models import Notification

        self.cancel(self.order(billed_to_parent=self.parent))
        notification = Notification.objects.get(type=Notification.Type.PAYMENT)
        self.assertEqual(notification.parent, self.parent)
        self.assertIsNone(notification.student)

    def test_voiding_an_unpaid_bill_says_it_was_cancelled_not_refunded(self):
        # 낸 적이 없으면 돌려받을 것도 없다 — 환불이라고 하면 돈을 기다린다.
        from apps.notifications.models import Notification

        order = Order.objects.create(
            student=self.student, product=self.product, amount=45000, is_billed=True
        )
        self.cancel(order)
        notification = Notification.objects.get(type=Notification.Type.PAYMENT)
        self.assertNotIn("환불", notification.body)
        self.assertIn("취소", notification.body)

    def test_a_bill_never_sent_notifies_nobody(self):
        # 학부모는 청구서를 받은 적이 없다 — 취소를 알릴 이유가 없다.
        from apps.notifications.models import Notification

        order = Order.objects.create(
            student=self.student, product=self.product, amount=45000, is_billed=False
        )
        self.cancel(order)
        self.assertFalse(Notification.objects.filter(type=Notification.Type.PAYMENT).exists())


@override_settings(PAYMENT_PROVIDER_BACKEND=RECORDING)
class NotificationFailureTests(TestCase):
    """**알림이 못 나가도 환불은 되돌아가지 않는다.**

    2026-08-12 운영 실측: 취소가 업체·DB 에 다 반영된 **뒤** 알림 디스패치가
    `RuntimeError: Retry limit exceeded while trying to reconnect to the Celery
    result store` 로 터졌다(운영에 워커·브로커가 아직 없다). 트랜잭션은 이미
    커밋된 뒤라 **돈은 돌아갔는데 화면에는 "취소하지 못했습니다"** 가 떴다.

    관리자는 실패로 읽고 다시 누른다 — 두 번째는 "이미 취소된 주문"이라
    이중 환불은 안 나지만, **무엇이 진짜인지 알 수 없는 화면**이 남는다.

    알림 행은 디스패치 **전에** 만들어지므로(sending.queue), 여기서 예외를
    삼켜도 재발송 배치가 그 행을 집어 간다 — 조용한 실패가 아니다.
    """

    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user("nf-own", User.Role.OWNER, name="대표")
        cls.product = Product.objects.create(name="로직엔제 교재 Vol.1", price=45000)
        cls.student = Student.objects.create(
            user=make_user("nf-stu", User.Role.STUDENT, name="김하늘"),
            matching_key="3_0001",
        )

    def test_cancel_survives_a_broken_notification_dispatch(self):
        from unittest.mock import patch

        order = Order.objects.create(
            student=self.student, product=self.product, amount=45000,
            status=Order.Status.PAID, is_billed=True,
        )
        Payment.objects.create(
            order=order, provider=Payment.Provider.PAYSSAM,
            status=Payment.Status.COMPLETED, amount=45000,
        )
        self.client.force_login(self.owner)
        with patch(
            "apps.payments.payment_admin.queue",
            side_effect=RuntimeError("Retry limit exceeded"),
        ):
            response = self.client.post(
                f"/api/admin/payments/{order.order_id}/cancel", {"reason": "환불"}
            )
        self.assertEqual(response.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CANCELLED)


@override_settings(PAYMENT_PROVIDER_BACKEND=RECORDING)
class ClassDeliveryTests(TestCase):
    """반 단위 교재 배부 — 러셀에 찍을 행을 만드는 자리 (FLOW 2-5·2-7·§5).

    **러셀 반은 청구가 막혀 있어 `Order` 가 안 생긴다.** 배부 표시는 `Order` 에
    붙으므로 일괄 배부가 필요한 바로 그 반이 통째로 비어 있었다. 여기서 행을
    만들되 **업체는 부르지 않는다** — 돈은 학원이 따로 받았다.

    되돌리기도 같은 커밋에 있다(§5). 배부 표시는 우리 장부라 밖으로 나가는
    것이 없고, 청구 취소처럼 문자를 한 통 더 낳지 않는다.
    """

    @classmethod
    def setUpTestData(cls):
        cls.admin = make_user("cd-adm", User.Role.ADMIN, name="관리자")
        StaffFeatureGrant.objects.create(
            user=cls.admin, feature_key=FeatureKey.PAYMENT_CHECK, is_granted=True
        )
        cls.subject, _ = Subject.objects.get_or_create(track="수능", name="통합과학")
        cls.course = Course.objects.create(
            name="2026 여름 N제", subject=cls.subject, total_weeks=10
        )
        cls.product = Product.objects.create(
            course=cls.course, name="N제 세트", price=45000
        )
        cls.russell = Class.objects.create(
            course=cls.course, name="목 6.5 대치러셀", uses_payssam=False
        )
        cls.mirae = Class.objects.create(
            course=cls.course, name="화 6.5 미래탐구", uses_payssam=True
        )
        cls.students = []
        for i in range(3):
            student = Student.objects.create(
                user=make_user(f"cd-stu{i}", User.Role.STUDENT, name=f"학생{i}"),
                matching_key=f"학생{i}000{i}",
            )
            CourseEnrollment.objects.create(
                student=student, course=cls.course, klass=cls.russell
            )
            cls.students.append(student)

    def setUp(self):
        RecordingAdapter.calls.clear()
        self.client.force_login(self.admin)

    def deliver_url(self, klass):
        return f"/api/admin/payments/classes/{klass.class_id}/deliver"

    def undeliver_url(self, klass):
        return f"/api/admin/payments/classes/{klass.class_id}/undeliver"

    def test_bulk_delivery_creates_the_rows_russell_never_had(self):
        response = self.client.post(
            self.deliver_url(self.russell), {"product_id": self.product.product_id}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"delivered": 3, "skipped": 0})
        orders = Order.objects.filter(product=self.product)
        self.assertEqual(orders.count(), 3)
        self.assertEqual(orders.filter(status=Order.Status.DELIVERED).count(), 3)

    def test_bulk_delivery_never_calls_the_vendor(self):
        # 결제선생이 나가면 안 된다 — 그것이 이 반의 정의다(FLOW 2-7).
        self.client.post(
            self.deliver_url(self.russell), {"product_id": self.product.product_id}
        )
        self.assertEqual(RecordingAdapter.calls, [])
        orders = Order.objects.filter(product=self.product)
        self.assertEqual(orders.filter(is_billed=True).count(), 0)
        self.assertEqual(Payment.objects.filter(order__in=orders).count(), 0)

    def test_bulk_delivery_is_idempotent(self):
        body = {"product_id": self.product.product_id}
        self.client.post(self.deliver_url(self.russell), body)
        second = self.client.post(self.deliver_url(self.russell), body)
        self.assertEqual(second.json(), {"delivered": 0, "skipped": 0})
        self.assertEqual(Order.objects.filter(product=self.product).count(), 3)

    def test_undo_leaves_the_purchase_but_drops_the_delivery(self):
        body = {"product_id": self.product.product_id}
        self.client.post(self.deliver_url(self.russell), body)
        response = self.client.post(self.undeliver_url(self.russell), body)
        self.assertEqual(response.json(), {"undelivered": 3})
        orders = Order.objects.filter(product=self.product)
        self.assertEqual(orders.filter(status=Order.Status.PAID).count(), 3)
        self.assertEqual(orders.exclude(delivered_at=None).count(), 0)

    def test_undo_sends_nothing_to_anyone(self):
        body = {"product_id": self.product.product_id}
        self.client.post(self.deliver_url(self.russell), body)
        before = Notification.objects.count()
        self.client.post(self.undeliver_url(self.russell), body)
        self.assertEqual(RecordingAdapter.calls, [])
        self.assertEqual(Notification.objects.count(), before)

    def test_cancelling_a_russell_order_never_calls_the_vendor(self):
        # 청구서가 나간 적 없는 `결제완료` 다 — 상태만 보고 승인취소를 걸면
        # 없는 청구서 때문에 실패해 오등록 행을 영영 못 지운다.
        self.client.post(
            self.deliver_url(self.russell), {"product_id": self.product.product_id}
        )
        order = Order.objects.filter(product=self.product).first()
        owner = make_user("cd-own", User.Role.OWNER, name="대표")
        self.client.force_login(owner)
        response = self.client.post(
            f"/api/admin/payments/{order.order_id}/cancel", {"reason": "오등록"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(RecordingAdapter.calls, [])

    def test_payssam_class_gets_no_invented_purchases(self):
        # 안 낸 학생을 결제완료로 세우면 받은 적 없는 돈이 장부에 선다.
        for student in self.students:
            CourseEnrollment.objects.filter(student=student).update(klass=self.mirae)
        response = self.client.post(
            self.deliver_url(self.mirae), {"product_id": self.product.product_id}
        )
        self.assertEqual(response.json(), {"delivered": 0, "skipped": 3})
        self.assertEqual(Order.objects.filter(product=self.product).count(), 0)

    def test_a_product_from_another_course_is_rejected(self):
        other = Course.objects.create(
            name="내신 생명", subject=self.subject, total_weeks=8
        )
        stray = Product.objects.create(course=other, name="남의 교재", price=10000)
        response = self.client.post(
            self.deliver_url(self.russell), {"product_id": stray.product_id}
        )
        self.assertEqual(response.status_code, 400)

    def test_bulk_delivery_needs_the_payment_feature(self):
        self.client.force_login(make_user("cd-ast", User.Role.ASSISTANT))
        response = self.client.post(
            self.deliver_url(self.russell), {"product_id": self.product.product_id}
        )
        self.assertEqual(response.status_code, 403)

    def test_single_delivery_can_be_undone(self):
        self.client.post(
            self.deliver_url(self.russell), {"product_id": self.product.product_id}
        )
        order = Order.objects.filter(product=self.product).first()
        response = self.client.post(f"/api/admin/payments/{order.order_id}/undeliver")
        self.assertEqual(response.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PAID)
        self.assertIsNone(order.delivered_at)
        # 배부완료가 아닌 것은 되돌릴 것이 없다.
        self.assertEqual(
            self.client.post(f"/api/admin/payments/{order.order_id}/undeliver").status_code,
            400,
        )

    def test_the_class_view_shows_who_holds_what(self):
        self.client.post(
            self.deliver_url(self.russell), {"product_id": self.product.product_id}
        )
        body = self.client.get(
            f"/api/admin/payments/classes/{self.russell.class_id}"
        ).json()
        self.assertFalse(body["class"]["uses_payssam"])
        self.assertEqual(len(body["students"]), 3)
        self.assertEqual([p["product_id"] for p in body["products"]], [self.product.product_id])
        held = body["students"][0]["orders"][str(self.product.product_id)]
        self.assertEqual(held["status"], Order.Status.DELIVERED)
        self.assertFalse(held["is_billed"])

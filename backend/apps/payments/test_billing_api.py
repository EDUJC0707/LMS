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
from apps.curriculum.models import Class, Course, CourseEnrollment
from apps.notifications.models import Notification

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
ADMIN_URL = "/api/admin/payments/bill"
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


def make_class(course_name, class_name, *, uses_payssam=True):
    """커리 + 반 한 쌍. 교재는 커리에 붙고(FLOW 1-6) 청구는 반이 연다(FLOW 2-7)."""
    course = Course.objects.create(name=course_name)
    return course, Class.objects.create(
        course=course, name=class_name, uses_payssam=uses_payssam
    )


@override_settings(PAYMENT_PROVIDER_BACKEND=RECORDING)
class BillingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.course, cls.klass = make_class("로직엔제", "수요반")
        cls.product = Product.objects.create(
            course=cls.course, name="로직엔제 교재 Vol.1", price=45000
        )
        cls.retired = Product.objects.create(
            course=cls.course, name="폐기 교재", price=1000, is_active=False
        )

        cls.student_user = make_user(
            "bl-stu", User.Role.STUDENT, name="김하늘", phone="01012345678"
        )
        cls.student = Student.objects.create(user=cls.student_user, matching_key="3_0001")
        cls.other_student = Student.objects.create(
            user=make_user("bl-stu2", User.Role.STUDENT), matching_key="3_0002"
        )
        for student in (cls.student, cls.other_student):
            CourseEnrollment.objects.create(
                student=student, course=cls.course, klass=cls.klass
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

    # -- 청구 알림(FLOW 3-11 #2) --------------------------------------------

    def test_billing_tells_the_recipient_what_the_bill_is_for(self):
        # 결제선생 문자에는 금액과 링크만 있고 어느 교재인지가 없다.
        self.client.force_login(self.parent_user)
        self.client.post(PARENT_URL, {"product_id": self.product.product_id})
        order = Order.objects.get(student=self.student)
        row = Notification.objects.get(type=Notification.Type.BILLING)
        self.assertEqual(row.parent_id, self.parent.parent_id)
        self.assertIsNone(row.student_id)
        self.assertIn(self.product.name, row.body)
        self.assertEqual((row.ref_type, row.ref_id), ("orders", order.order_id))

    def test_a_student_paying_for_himself_is_the_one_told(self):
        self.client.force_login(self.student_user)
        self.start()
        row = Notification.objects.get(type=Notification.Type.BILLING)
        self.assertEqual(row.student_id, self.student.student_id)

    def test_the_second_click_does_not_queue_a_second_notification(self):
        self.client.force_login(self.student_user)
        self.start()
        self.start()
        self.assertEqual(Notification.objects.filter(type=Notification.Type.BILLING).count(), 1)

    def test_a_refused_bill_tells_nobody(self):
        # 청구서가 안 나갔는데 "청구했습니다" 가 가면 안 된다.
        with override_settings(PAYMENT_PROVIDER_BACKEND=FAILING_PERMANENT):
            self.client.force_login(self.student_user)
            self.start()
        self.assertFalse(Notification.objects.filter(type=Notification.Type.BILLING).exists())

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
        # 사유 문장은 여기서 보지 않는다 — 업체 사유는 로그로만 간다
        # (VendorReasonTests). 여기서 지키는 것은 플래그가 안 섰다는 사실뿐이다.
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


@override_settings(PAYMENT_PROVIDER_BACKEND=FAILING_PERMANENT)
class VendorReasonTests(TestCase):
    """업체 실패 사유는 **운영 정보**다 — 소비자 화면에 그대로 흘리지 않는다.

    쌤포인트 잔액이 마르면 업체가 `POINT_001`("포인트가 부족합니다")로 거절한다.
    그 문장을 학생에게 그대로 보여 주면 ① 학생은 무슨 말인지 알 수 없고
    ② **정작 충전해야 하는 관리자는 그 사실을 영영 모른다**(자동충전을 안 켜기로
    한 2026-08-11 결정이라 사람이 알아야 풀린다).
    """

    @classmethod
    def setUpTestData(cls):
        course, klass = make_class("로직엔제", "수요반")
        cls.product = Product.objects.create(
            course=course, name="로직엔제 교재 Vol.1", price=45000
        )
        cls.user = make_user("vr-stu", User.Role.STUDENT, name="김하늘", phone="01012345678")
        student = Student.objects.create(user=cls.user, matching_key="3_7001")
        CourseEnrollment.objects.create(student=student, course=course, klass=klass)

    def test_vendor_reason_is_not_shown_to_the_student(self):
        self.client.force_login(self.user)
        response = self.client.post(
            STUDENT_URL, {"product_id": self.product.product_id}
        )
        self.assertEqual(response.status_code, 502)
        self.assertNotIn("포인트", response.json()["detail"])

    def test_vendor_reason_is_logged_for_the_operator(self):
        self.client.force_login(self.user)
        with self.assertLogs("apps.payments.views", level="ERROR") as captured:
            self.client.post(STUDENT_URL, {"product_id": self.product.product_id})
        self.assertTrue(any("포인트가 부족합니다" in line for line in captured.output))


@override_settings(PAYMENT_PROVIDER_BACKEND=RECORDING)
class PayssamOffTests(TestCase):
    """**결제선생을 안 쓰는 반에서는 청구가 나가지 않는다**(FLOW 2-7).

    러셀은 교재값을 학원이 따로 받는다. 여기서 안 막으면 조교의 기억이 유일한
    안전장치가 되고, 한 번 잘못 누르면 학부모가 같은 교재값을 두 번 낸다 —
    되돌려도 학부모는 이미 청구서를 받은 뒤다.

    세 경로(학생·학부모·관리자)를 다 본다. 판정이 `start_billing` 한 곳에
    있으므로 셋이 같이 막히거나 같이 새는 것이지, 한 경로만 막는 방어는 없다.
    """

    @classmethod
    def setUpTestData(cls):
        course, klass = make_class("러셀 통합과학", "러셀 목요반", uses_payssam=False)
        cls.product = Product.objects.create(
            course=course, name="러셀 N제", price=30000
        )
        cls.student_user = make_user(
            "off-stu", User.Role.STUDENT, name="박러셀", phone="01011112222"
        )
        cls.student = Student.objects.create(user=cls.student_user, matching_key="3_6001")
        CourseEnrollment.objects.create(student=cls.student, course=course, klass=klass)
        cls.parent_user = make_user("off-par", User.Role.PARENT)
        cls.parent = Parent.objects.create(user=cls.parent_user, phone="01033334444")
        ParentStudent.objects.create(parent=cls.parent, student=cls.student)
        cls.admin = make_user("off-adm", User.Role.ADMIN)
        cls.klass = klass

    def setUp(self):
        RecordingAdapter.sent.clear()

    def _bill(self, url, user, **extra):
        self.client.force_login(user)
        return self.client.post(url, {"product_id": self.product.product_id, **extra})

    def test_student_click_is_refused(self):
        response = self._bill(STUDENT_URL, self.student_user)
        self.assertEqual(response.status_code, 400)
        self.assertIn("결제선생", response.json()["detail"])

    def test_parent_click_is_refused(self):
        self.assertEqual(self._bill(PARENT_URL, self.parent_user).status_code, 400)

    def test_admin_click_is_refused(self):
        response = self._bill(
            ADMIN_URL, self.admin, student_id=self.student.student_id
        )
        self.assertEqual(response.status_code, 400)

    def test_nothing_reaches_the_vendor_and_no_order_is_left_behind(self):
        # 업체 호출이 없어야 쌤포인트도 안 타고, 주문 행이 없어야 관리 화면에
        # 누른 적 없는 `미청구` 가 쌓이지 않는다.
        self._bill(STUDENT_URL, self.student_user)
        self._bill(ADMIN_URL, self.admin, student_id=self.student.student_id)
        self.assertEqual(RecordingAdapter.sent, [])
        self.assertFalse(Order.objects.filter(student=self.student).exists())

    def test_turning_it_on_lets_the_same_click_through(self):
        # 막힌 것이 영구 차단이 아니라 반 설정이라는 것 — 조교가 켜면 나간다.
        self.klass.uses_payssam = True
        self.klass.save(update_fields=["uses_payssam"])
        self.assertEqual(self._bill(STUDENT_URL, self.student_user).status_code, 201)
        self.assertEqual(len(RecordingAdapter.sent), 1)

    def test_a_class_without_a_klass_row_is_refused(self):
        # 반이 안 붙은 수강은 "결제선생을 쓰는 반" 이라는 근거가 없는 것이다.
        loose = Student.objects.create(
            user=make_user("off-stu2", User.Role.STUDENT, phone="01055556666"),
            matching_key="3_6002",
        )
        CourseEnrollment.objects.create(
            student=loose, course=self.product.course, klass=None
        )
        self.client.force_login(loose.user)
        response = self.client.post(
            STUDENT_URL, {"product_id": self.product.product_id}
        )
        self.assertEqual(response.status_code, 400)


@override_settings(PAYMENT_PROVIDER_BACKEND=RECORDING)
class OtherCourseProductTests(TestCase):
    """**다른 커리의 교재로는 청구가 안 된다**(FLOW 1-6).

    목록만 좁히면 소용이 없다 — 청구는 `product_id` 를 본문으로 받으므로 목록을
    안 거치고 들어올 수 있다. 그래서 판정은 `start_billing` 에 있다.
    """

    @classmethod
    def setUpTestData(cls):
        cls.mine, mine_class = make_class("수능 통합과학", "수요반")
        other, _ = make_class("내신 생명과학", "금요반")
        cls.other_product = Product.objects.create(
            course=other, name="내신 생명과학 교재", price=20000
        )
        cls.orphan = Product.objects.create(name="커리 미지정 교재", price=10000)
        cls.user = make_user("oc-stu", User.Role.STUDENT, phone="01012341234")
        student = Student.objects.create(user=cls.user, matching_key="3_5001")
        CourseEnrollment.objects.create(
            student=student, course=cls.mine, klass=mine_class
        )

    def setUp(self):
        RecordingAdapter.sent.clear()
        self.client.force_login(self.user)

    def test_billing_another_course_product_is_refused(self):
        response = self.client.post(
            STUDENT_URL, {"product_id": self.other_product.product_id}
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(RecordingAdapter.sent, [])

    def test_billing_a_product_with_no_course_is_refused(self):
        # 커리가 비어 있는 행은 아무에게도 안 보인다 — 닫힘이 안전 기본값.
        response = self.client.post(
            STUDENT_URL, {"product_id": self.orphan.product_id}
        )
        self.assertEqual(response.status_code, 400)


@override_settings(PAYMENT_PROVIDER_BACKEND=RECORDING)
class SiblingBillNameTests(TestCase):
    """**형제 청구서에 각자 자기 이름이 찍힌다**(FLOW 2-4).

    형제는 묶지 않는다 — 아이디마다 따로 청구가 나간다. 그러면 학부모는 같은
    교재 청구를 두 건 받고, **어느 아이 것인지 이름으로만 가른다.** 학부모
    계정의 `user.name` 은 최초 연결 자녀 기준으로 고정되므로(provisioning),
    그쪽을 쓰면 둘째 청구서에 첫째 이름이 찍혀 두 문자가 완전히 같아진다.
    남의 자녀 이름이 실린 청구서라 개인정보 축도 걸린다.

    여기서 보는 `customer_name` 이 결제선생 `memberName` 이다
    (test_payssam.py 의 매핑 검증이 그 자리를 고정한다).
    """

    @classmethod
    def setUpTestData(cls):
        course, klass = make_class("로직엔제", "수요반")
        cls.product = Product.objects.create(
            course=course, name="로직엔제 교재 Vol.1", price=45000
        )
        # 첫째가 계정을 만들게 했으므로 학부모 user.name 은 `김첫째 학부모` 로
        # 굳는다 — 둘째 청구서가 그 이름을 물려받으면 안 된다.
        cls.parent_user = make_user("sib-par", User.Role.PARENT, name="김첫째 학부모")
        cls.parent = Parent.objects.create(user=cls.parent_user, phone="01099998888")
        cls.children = []
        for idx, name in enumerate(("김첫째", "김둘째"), start=1):
            student = Student.objects.create(
                user=make_user(f"sib-stu{idx}", User.Role.STUDENT, name=name),
                matching_key=f"3_400{idx}",
            )
            CourseEnrollment.objects.create(student=student, course=course, klass=klass)
            ParentStudent.objects.create(parent=cls.parent, student=student)
            cls.children.append(student)

    def setUp(self):
        RecordingAdapter.sent.clear()
        self.client.force_login(self.parent_user)

    def test_each_child_bill_carries_that_child_name(self):
        for student in self.children:
            self.client.post(
                PARENT_URL,
                {
                    "product_id": self.product.product_id,
                    "student_id": student.student_id,
                },
            )
        names = [request.customer_name for request in RecordingAdapter.sent]
        self.assertEqual(names, ["김첫째 학부모", "김둘째 학부모"])
        self.assertEqual(len(set(names)), 2)

    def test_admin_route_names_the_child_too(self):
        # 관리자가 보낸 것도 같은 자리를 쓴다 — 경로마다 이름이 달라지면 안 된다.
        self.client.force_login(make_user("sib-adm", User.Role.ADMIN))
        self.client.post(
            ADMIN_URL,
            {
                "product_id": self.product.product_id,
                "student_id": self.children[1].student_id,
            },
        )
        self.assertEqual(RecordingAdapter.sent[0].customer_name, "김둘째 학부모")


@override_settings(PAYMENT_PROVIDER_BACKEND=RECORDING)
class AdminBillTests(TestCase):
    """POST /api/admin/payments/bill — 관리자가 청구를 시작한다(FLOW 2-4·2-5).

    이 라우트가 없어서 조교는 청구를 시작할 수 없었다. 게이트는 기능 키
    `결제확인` 이고 조교 프리셋에는 없다 — 대표가 delta 로만 연다.
    """

    @classmethod
    def setUpTestData(cls):
        course, klass = make_class("로직엔제", "수요반")
        cls.product = Product.objects.create(
            course=course, name="로직엔제 교재 Vol.1", price=45000
        )
        cls.student = Student.objects.create(
            user=make_user("ab-stu", User.Role.STUDENT, name="김하늘", phone="01012345678"),
            matching_key="3_3001",
        )
        CourseEnrollment.objects.create(
            student=cls.student, course=course, klass=klass
        )
        cls.parent = Parent.objects.create(
            user=make_user("ab-par", User.Role.PARENT), phone="01099998888"
        )
        ParentStudent.objects.create(parent=cls.parent, student=cls.student)
        cls.admin = make_user("ab-adm", User.Role.ADMIN)
        cls.assistant = make_user("ab-asi", User.Role.ASSISTANT)

    def setUp(self):
        RecordingAdapter.sent.clear()

    def _post(self, **payload):
        payload.setdefault("product_id", self.product.product_id)
        payload.setdefault("student_id", self.student.student_id)
        return self.client.post(ADMIN_URL, payload)

    def test_assistant_is_blocked_without_the_feature_key(self):
        self.client.force_login(self.assistant)
        self.assertEqual(self._post().status_code, 403)

    def test_student_cannot_use_the_admin_route(self):
        self.client.force_login(self.student.user)
        self.assertEqual(self._post().status_code, 403)

    def test_admin_starts_billing_and_it_goes_to_the_parent(self):
        self.client.force_login(self.admin)
        response = self._post()
        self.assertEqual(response.status_code, 201)
        order = Order.objects.get(student=self.student, product=self.product)
        self.assertTrue(order.is_billed)
        self.assertEqual(order.billed_to_parent, self.parent)
        self.assertEqual(RecordingAdapter.sent[0].phone, "01099998888")

    def test_second_send_does_not_resend(self):
        self.client.force_login(self.admin)
        self.assertEqual(self._post().status_code, 201)
        self.assertEqual(self._post().status_code, 200)
        self.assertEqual(len(RecordingAdapter.sent), 1)

    def test_unknown_student_is_404(self):
        self.client.force_login(self.admin)
        self.assertEqual(self._post(student_id=999999).status_code, 404)

    def test_student_without_a_parent_falls_back_to_their_own_phone(self):
        alone = Student.objects.create(
            user=make_user("ab-stu2", User.Role.STUDENT, phone="01077778888"),
            matching_key="3_3002",
        )
        CourseEnrollment.objects.create(
            student=alone,
            course=self.product.course,
            klass=self.product.course.classes.get(),
        )
        self.client.force_login(self.admin)
        self.assertEqual(self._post(student_id=alone.student_id).status_code, 201)
        self.assertEqual(RecordingAdapter.sent[0].phone, "01077778888")

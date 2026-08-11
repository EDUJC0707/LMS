"""교재 결제 소비자 조회 API 테스트 — PRD 3.2.5(내 결제·배부 상태), 3.4(학부모).

**이 파일이 이 트랙의 완료 판정이다.** 영상 트랙이 2026-08-04 에 겪은 것:
관리 화면·권한 모델·자동 지급이 다 서 있었는데 **소비를 막는 코드가 한 줄도
없어서** 번호만 알면 남의 것을 볼 수 있었다. "관리 쪽이 다 됐다"를 완료로
착각한 것이 원인이라, 여기서는 **게이트를 지나는 테스트**를 먼저 세운다.

검증 축:
- 학생은 **자기 주문만** 본다(남의 주문은 목록에도 상세에도 없다)
- 학부모는 **연결된 자녀만** 본다(소유 밖 student_id 는 404 — 존재를 노출하지
  않는다. grades·curriculum 의 `_resolve_child` 선례와 같은 판정)
- 직원·비로그인은 소비자 경로에 들어오지 못한다(닫힘이 기본값)
- 예비등록생(미등록)도 결제는 보인다 — PRD §4 상태 기반 노출에서 미등록에게
  열려 있는 것이 **교재 구매**다
"""
from django.test import TestCase

from apps.accounts.models import Parent, ParentStudent, Student, User

from .models import Order, Payment, Product

PASSWORD = "pw-Secret-77!"
STUDENT_URL = "/api/student/payments"
PARENT_URL = "/api/parent/payments"


def make_user(login_id, role, name="사용자"):
    return User.objects.create_user(
        login_id=login_id, password=PASSWORD, name=name, role=role
    )


class ConsumerPaymentsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.product = Product.objects.create(name="로직엔제 교재 Vol.1", price=45000)
        cls.other_product = Product.objects.create(name="심화 교재", price=32000)

        cls.student_user = make_user("pay-stu", User.Role.STUDENT, name="김하늘")
        cls.student = Student.objects.create(user=cls.student_user, matching_key="3_0001")

        cls.other_user = make_user("pay-stu2", User.Role.STUDENT, name="남의학생")
        cls.other_student = Student.objects.create(
            user=cls.other_user, matching_key="3_0002"
        )

        cls.parent_user = make_user("pay-par", User.Role.PARENT, name="학부모")
        cls.parent = Parent.objects.create(user=cls.parent_user, phone="01011119999")
        ParentStudent.objects.create(parent=cls.parent, student=cls.student)

        cls.stranger_parent_user = make_user("pay-par2", User.Role.PARENT, name="남의학부모")
        cls.stranger_parent = Parent.objects.create(
            user=cls.stranger_parent_user, phone="01022228888"
        )
        ParentStudent.objects.create(
            parent=cls.stranger_parent, student=cls.other_student
        )

        cls.staff = make_user("pay-adm", User.Role.ADMIN, name="관리자")

        cls.my_order = Order.objects.create(
            student=cls.student, product=cls.product, amount=45000
        )
        cls.other_order = Order.objects.create(
            student=cls.other_student, product=cls.product, amount=45000
        )

    # -- 게이트 -------------------------------------------------------------

    def test_anonymous_cannot_read_payments(self):
        self.assertEqual(self.client.get(STUDENT_URL).status_code, 403)

    def test_staff_cannot_use_the_student_route(self):
        # 직원은 관리자 경로를 쓴다. 소비자 경로는 역할군으로 닫는다.
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(STUDENT_URL).status_code, 403)

    def test_parent_cannot_use_the_student_route(self):
        self.client.force_login(self.parent_user)
        self.assertEqual(self.client.get(STUDENT_URL).status_code, 403)

    def test_student_cannot_use_the_parent_route(self):
        self.client.force_login(self.student_user)
        self.assertEqual(self.client.get(PARENT_URL).status_code, 403)

    # -- 학생: 자기 것만 ----------------------------------------------------

    def test_student_sees_only_own_orders(self):
        self.client.force_login(self.student_user)
        rows = self.client.get(STUDENT_URL).json()
        self.assertEqual([row["order_id"] for row in rows], [self.my_order.order_id])

    def test_student_row_carries_the_status_the_screen_shows(self):
        self.client.force_login(self.student_user)
        row = self.client.get(STUDENT_URL).json()[0]
        self.assertEqual(row["product_name"], "로직엔제 교재 Vol.1")
        self.assertEqual(row["amount"], 45000)
        self.assertEqual(row["status"], Order.Status.UNPAID)
        self.assertIsNone(row["paid_at"])

    def test_student_without_a_student_row_gets_an_empty_list(self):
        # 학생 role 인데 students 행이 없는 예외 상태 — 500 이 아니라 빈 목록이다.
        bare = make_user("pay-bare", User.Role.STUDENT)
        self.client.force_login(bare)
        response = self.client.get(STUDENT_URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_paid_order_exposes_when_it_was_paid(self):
        from django.utils import timezone

        now = timezone.now()
        order = Order.objects.create(
            student=self.student,
            product=self.other_product,
            amount=32000,
            status=Order.Status.PAID,
            paid_at=now,
        )
        Payment.objects.create(
            order=order,
            provider=Payment.Provider.PAYSSAM,
            status=Payment.Status.COMPLETED,
            amount=32000,
            paid_at=now,
        )
        self.client.force_login(self.student_user)
        rows = {row["order_id"]: row for row in self.client.get(STUDENT_URL).json()}
        self.assertEqual(rows[order.order_id]["status"], Order.Status.PAID)
        self.assertIsNotNone(rows[order.order_id]["paid_at"])

    # -- 학부모: 연결된 자녀만 ----------------------------------------------

    def test_parent_sees_the_linked_child_orders(self):
        self.client.force_login(self.parent_user)
        rows = self.client.get(PARENT_URL).json()
        self.assertEqual([row["order_id"] for row in rows], [self.my_order.order_id])

    def test_parent_can_select_a_linked_child_explicitly(self):
        self.client.force_login(self.parent_user)
        response = self.client.get(f"{PARENT_URL}?student_id={self.student.student_id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [row["order_id"] for row in response.json()], [self.my_order.order_id]
        )

    def test_parent_cannot_read_a_child_that_is_not_theirs(self):
        # 소유 밖 student_id 는 **404** — 403 으로 갈리면 "그 번호의 학생은
        # 존재한다"가 새어 나간다(§4 상태 기반 노출, grades 선례).
        self.client.force_login(self.parent_user)
        response = self.client.get(
            f"{PARENT_URL}?student_id={self.other_student.student_id}"
        )
        self.assertEqual(response.status_code, 404)

    def test_nonexistent_child_id_is_also_404(self):
        # 존재하는 남의 자녀와 없는 번호가 같은 응답이어야 존재가 안 새어 나간다.
        self.client.force_login(self.parent_user)
        self.assertEqual(self.client.get(f"{PARENT_URL}?student_id=999999").status_code, 404)

    def test_malformed_child_id_is_rejected(self):
        self.client.force_login(self.parent_user)
        self.assertEqual(self.client.get(f"{PARENT_URL}?student_id=abc").status_code, 400)

    def test_parent_without_a_parent_row_is_404(self):
        bare = make_user("pay-bare-par", User.Role.PARENT)
        self.client.force_login(bare)
        self.assertEqual(self.client.get(PARENT_URL).status_code, 404)


class ProductListTests(TestCase):
    """GET /api/payments/products — 살 수 있는 교재 목록.

    청구 개시가 `product_id` 를 받는데 그 번호를 소비자에게 알려 주는 자리가
    없었다 — 목록이 없으면 구매 버튼을 그릴 수 없다(videos 목록 선례).
    학생·학부모가 같은 목록을 본다(교재는 학생별로 다르지 않다).
    """

    URL = "/api/payments/products"

    @classmethod
    def setUpTestData(cls):
        cls.live = Product.objects.create(name="로직엔제 교재 Vol.1", price=45000)
        cls.retired = Product.objects.create(name="폐기 교재", price=1000, is_active=False)
        cls.student_user = make_user("prod-stu", User.Role.STUDENT)
        Student.objects.create(user=cls.student_user, matching_key="3_9001")
        cls.parent_user = make_user("prod-par", User.Role.PARENT)
        Parent.objects.create(user=cls.parent_user, phone="01055556666")

    def test_anonymous_is_blocked(self):
        self.assertEqual(self.client.get(self.URL).status_code, 403)

    def test_student_sees_only_products_on_sale(self):
        self.client.force_login(self.student_user)
        rows = self.client.get(self.URL).json()
        self.assertEqual([r["product_id"] for r in rows], [self.live.product_id])
        self.assertEqual(rows[0]["name"], "로직엔제 교재 Vol.1")
        self.assertEqual(rows[0]["price"], 45000)

    def test_parent_sees_the_same_list(self):
        self.client.force_login(self.parent_user)
        rows = self.client.get(self.URL).json()
        self.assertEqual([r["product_id"] for r in rows], [self.live.product_id])

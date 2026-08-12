"""관리자 교재 결제 조회 API 테스트 — GET /api/admin/payments (PRD 3.1.5).

PRD 요구: *"관리자가 학생별 교재 구매/결제 상태(완료·미결제·배부)를 조회"*.

이 화면이 없으면 결제선생에서 동기화된 상태가 DB 에만 쌓이고 **배부할 사람을
고를 방법이 없다**(as-is 가 "결제내역 확인 후 배부"다).

게이트는 기능 키 `결제확인`(FeatureKey.PAYMENT_CHECK)이다 — 조교는 프리셋에
없으므로 기본 차단이고, 대표가 delta 로만 연다(key_considerations §2).
"""
import datetime

from django.test import TestCase
from django.utils import timezone

from apps.accounts.features import FeatureKey
from apps.accounts.models import StaffFeatureGrant, Student, User

from .models import Order, Payment, Product

URL = "/api/admin/payments"
PASSWORD = "pw-Secret-77!"


def make_user(login_id, role, name="사용자"):
    return User.objects.create_user(
        login_id=login_id, password=PASSWORD, name=name, role=role
    )


class AdminPaymentsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user("pa-own", User.Role.OWNER, name="대표")
        cls.admin = make_user("pa-adm", User.Role.ADMIN, name="관리자")
        cls.assistant = make_user("pa-ast", User.Role.ASSISTANT, name="조교")
        cls.student_user = make_user("pa-stu", User.Role.STUDENT, name="김하늘")

        cls.product = Product.objects.create(name="로직엔제 교재 Vol.1", price=45000)
        cls.other_product = Product.objects.create(name="심화 교재", price=32000)

        cls.hanul = Student.objects.create(user=cls.student_user, matching_key="3_0001")
        # 계정 발급 전 학생 — 이름은 users 행이 든다. 없으면 원번으로 떨어져야 한다.
        cls.nameless = Student.objects.create(matching_key="3_0002")

        cls.unpaid = Order.objects.create(
            student=cls.hanul, product=cls.product, amount=45000, is_billed=True
        )
        cls.paid = Order.objects.create(
            student=cls.nameless,
            product=cls.product,
            amount=45000,
            status=Order.Status.PAID,
            paid_at=timezone.now(),
            is_billed=True,
        )
        Payment.objects.create(
            order=cls.paid,
            provider=Payment.Provider.PAYSSAM,
            status=Payment.Status.COMPLETED,
            amount=45000,
            external_ref="APPR-77",
            paid_at=timezone.now(),
        )

    def login(self, user=None):
        self.client.force_login(user or self.admin)

    # -- 게이트 -------------------------------------------------------------

    def test_anonymous_is_blocked(self):
        self.assertEqual(self.client.get(URL).status_code, 403)

    def test_student_is_blocked(self):
        self.client.force_login(self.student_user)
        self.assertEqual(self.client.get(URL).status_code, 403)

    def test_assistant_is_blocked_by_default(self):
        # 조교 프리셋에 `결제확인` 이 없다 — 닫힘이 기본값.
        self.client.force_login(self.assistant)
        self.assertEqual(self.client.get(URL).status_code, 403)

    def test_assistant_with_a_granted_feature_passes(self):
        # 대표가 delta 로 열면 통과한다(프리셋 ⊕ delta).
        StaffFeatureGrant.objects.create(
            user=self.assistant, feature_key=FeatureKey.PAYMENT_CHECK, is_granted=True
        )
        self.client.force_login(self.assistant)
        self.assertEqual(self.client.get(URL).status_code, 200)

    def test_admin_preset_includes_payment_check(self):
        self.login()
        self.assertEqual(self.client.get(URL).status_code, 200)

    def test_owner_passes_without_any_grant(self):
        self.login(self.owner)
        self.assertEqual(self.client.get(URL).status_code, 200)

    def test_admin_with_the_feature_revoked_is_blocked(self):
        StaffFeatureGrant.objects.create(
            user=self.admin, feature_key=FeatureKey.PAYMENT_CHECK, is_granted=False
        )
        self.login()
        self.assertEqual(self.client.get(URL).status_code, 403)

    # -- 목록 ---------------------------------------------------------------

    def test_lists_every_students_order_newest_first(self):
        self.login()
        body = self.client.get(URL).json()
        self.assertEqual(
            [row["order_id"] for row in body["results"]],
            [self.paid.order_id, self.unpaid.order_id],
        )
        self.assertEqual(body["count"], 2)

    def test_row_carries_who_owes_what(self):
        self.login()
        rows = {r["order_id"]: r for r in self.client.get(URL).json()["results"]}
        row = rows[self.unpaid.order_id]
        self.assertEqual(row["student"]["name"], "김하늘")
        self.assertEqual(row["student"]["id"], self.hanul.student_id)
        self.assertEqual(row["product_name"], "로직엔제 교재 Vol.1")
        self.assertEqual(row["amount"], 45000)
        self.assertEqual(row["status"], Order.Status.UNPAID)
        self.assertTrue(row["is_billed"])

    def test_student_without_an_account_falls_back_to_the_matching_key(self):
        # students 에 name 컬럼이 없다 — 계정 발급 전이면 원번으로 떨어진다
        # (notification_admin `_target` 선례). 빈 이름을 내리면 화면에서 누구
        # 것인지 못 읽는다.
        self.login()
        rows = {r["order_id"]: r for r in self.client.get(URL).json()["results"]}
        self.assertEqual(rows[self.paid.order_id]["student"]["name"], "3_0002")

    def test_paid_row_exposes_the_neutral_external_reference(self):
        # 대사(reconciliation)의 근거다 — 업체 승인번호가 안 보이면 결제선생
        # 화면과 우리 목록을 맞춰 볼 수단이 없다.
        self.login()
        rows = {r["order_id"]: r for r in self.client.get(URL).json()["results"]}
        payment = rows[self.paid.order_id]["payment"]
        self.assertEqual(payment["external_ref"], "APPR-77")
        self.assertEqual(payment["provider"], Payment.Provider.PAYSSAM)
        self.assertEqual(payment["status"], Payment.Status.COMPLETED)

    def test_unpaid_row_has_no_payment_block(self):
        self.login()
        rows = {r["order_id"]: r for r in self.client.get(URL).json()["results"]}
        self.assertIsNone(rows[self.unpaid.order_id]["payment"])

    # -- 필터 ---------------------------------------------------------------

    def test_filters_by_status(self):
        self.login()
        body = self.client.get(f"{URL}?status={Order.Status.PAID}").json()
        self.assertEqual([r["order_id"] for r in body["results"]], [self.paid.order_id])

    def test_filters_by_student(self):
        self.login()
        body = self.client.get(f"{URL}?student_id={self.hanul.student_id}").json()
        self.assertEqual([r["order_id"] for r in body["results"]], [self.unpaid.order_id])

    def test_filters_by_billed_flag(self):
        unbilled = Order.objects.create(
            student=self.hanul, product=self.other_product, amount=32000, is_billed=False
        )
        self.login()
        body = self.client.get(f"{URL}?is_billed=false").json()
        self.assertEqual([r["order_id"] for r in body["results"]], [unbilled.order_id])

    def test_unknown_status_is_an_error_not_an_empty_list(self):
        # `status=결제완료함` 같은 오타가 빈 목록으로 돌아오면 "결제가 하나도
        # 없다"로 읽혀 정반대의 판단을 부른다(notification_admin 선례).
        self.login()
        response = self.client.get(f"{URL}?status=결제완료함")
        self.assertEqual(response.status_code, 400)

    def test_malformed_student_id_is_an_error(self):
        self.login()
        self.assertEqual(self.client.get(f"{URL}?student_id=abc").status_code, 400)

    def test_date_range_covers_the_end_day(self):
        # 관리자가 오늘까지 보려고 오늘을 적는다 — 끝 날짜는 그날을 포함한다.
        today = timezone.localdate()
        self.login()
        body = self.client.get(f"{URL}?from={today}&to={today}").json()
        self.assertEqual(body["count"], 2)

    def test_date_range_excludes_outside_days(self):
        today = timezone.localdate()
        yesterday = today - datetime.timedelta(days=1)
        self.login()
        body = self.client.get(f"{URL}?from={yesterday}&to={yesterday}").json()
        self.assertEqual(body["count"], 0)

    def test_malformed_date_is_an_error(self):
        self.login()
        self.assertEqual(self.client.get(f"{URL}?from=2026-13-99").status_code, 400)

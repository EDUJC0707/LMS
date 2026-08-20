"""payments 스모크 테스트 — 도메인 5(교재 결제) 핵심 계약 검증.

설계 근거: docs/db/lms-db-design-2026-07-15.md 도메인 5(+헤더 노트 ②
tuition_charges 삭제), §4.7(결제 중복 방지 인덱스), baseline lms-db-spec.html
Domain 5, PRD 3.1.5(양측 결제·sync)·3.2.5(교재 구매).
핵심은 부분 UQ(활성 청구 1건)와 Provider 추상화(업체 종속 컬럼 금지)다.
"""
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.test import TestCase

from apps.accounts.models import Student

from . import models as payments_models
from .models import Order, Payment, Product


def make_student(matching_key="3_1234"):
    return Student.objects.create(matching_key=matching_key)


def make_product(name="로직엔제 교재", price=45000):
    return Product.objects.create(name=name, price=price)


class ProductTests(TestCase):
    def test_table_and_pk_column_follow_design(self):
        self.assertEqual(Product._meta.db_table, "products")
        self.assertEqual(Product._meta.pk.column, "product_id")

    def test_defaults_follow_design(self):
        # baseline: is_active NN 기본 true(판매 여부 — 폐기는 soft-off)
        self.assertTrue(make_product().is_active)


class ProductCoverTests(TestCase):
    """표지 사진(FLOW 1-6) — 저장 계약은 워크북 사진(grades/workbook_admin.py)과 같다.

    쓰기 화면이 Django admin 하나뿐이라 검증을 모델 validator 로 건다. admin 의
    ModelForm 이 full_clean 을 부르므로 그 한 자리가 곧 조교가 만나는 경계다.
    """

    def upload(self, name, size=1024):
        return SimpleUploadedFile(name, b"x" * size, content_type="image/jpeg")

    def test_cover_is_capped_at_10mb_and_photo_formats_only(self):
        product = make_product()
        product.cover = self.upload("표지.jpg", size=payments_models.COVER_MAX_SIZE + 1)
        with self.assertRaises(ValidationError) as caught:
            product.full_clean()
        self.assertIn("파일 크기는 10MB 이하여야 합니다.", caught.exception.message_dict["cover"])

        # 브라우저가 그대로 못 그리는 포맷은 표지가 될 수 없다(워크북과 같은 넷)
        product.cover = self.upload("표지.pdf")
        with self.assertRaises(ValidationError):
            product.full_clean()

    def test_the_uploaded_name_never_becomes_the_path(self):
        """경로 주입 차단 — 원본명에서는 확장자만 가져온다(workbook_admin 과 같은 이유)."""
        product = make_product()
        product.cover = self.upload("../../etc/passwd.png")
        product.save()
        self.assertTrue(product.cover.name.startswith("product/covers/"))
        self.assertTrue(product.cover.name.endswith(".png"))
        self.assertNotIn("passwd", product.cover.name)


class OrderTests(TestCase):
    def setUp(self):
        self.student = make_student()
        self.product = make_product()

    def make_order(self, **kwargs):
        kwargs.setdefault("student", self.student)
        kwargs.setdefault("product", self.product)
        kwargs.setdefault("amount", self.product.price)
        return Order.objects.create(**kwargs)

    def test_table_and_pk_column_follow_design(self):
        self.assertEqual(Order._meta.db_table, "orders")
        self.assertEqual(Order._meta.pk.column, "order_id")

    def test_status_value_set_includes_cancel(self):
        # baseline 미결제/결제완료/배부완료 + 부분 UQ 전제인 `취소`(§4.7)
        self.assertEqual(
            set(Order.Status.values), {"미결제", "결제완료", "배부완료", "취소"}
        )

    def test_defaults_follow_design(self):
        # 설계: status 기본 미결제, is_billed NN 기본 false(청구서 발송 플래그)
        order = self.make_order()
        self.assertEqual(order.status, Order.Status.UNPAID)
        self.assertFalse(order.is_billed)
        self.assertIsNone(order.billed_at)
        self.assertIsNone(order.initiated_by_user)
        self.assertIsNone(order.billed_to_parent)
        self.assertIsNone(order.charge_trigger)
        self.assertIsNone(order.source_session)

    def test_charge_trigger_value_set(self):
        # 설계: 첫수업/수동 — 주차 반복 아님(교재 청구는 첫 수업 기준 1회)
        self.assertEqual(set(Order.ChargeTrigger.values), {"첫수업", "수동"})

    def test_active_order_unique_per_student_and_product(self):
        # 설계 §4.7 부분 UQ(student, product) WHERE status <> '취소':
        # 학생·학부모 어느 경로든 동일 학생·동일 교재 활성 청구는 1건 —
        # 중복 청구·결제 방지(sync)의 DB 강제 지점.
        self.make_order()
        with self.assertRaises(IntegrityError):
            self.make_order()

    def test_cancelled_order_allows_new_order(self):
        # 취소된 주문은 부분 UQ 대상에서 빠진다 — 취소 후 재청구 가능.
        self.make_order(status=Order.Status.CANCELLED)
        order = self.make_order()
        self.assertEqual(order.status, Order.Status.UNPAID)

    def test_sync_contract_documented(self):
        # PRD 3.1.5: is_billed = 청구서 발송 여부 플래그(양측 sync 판정 근거,
        # 중복 발송 차단). 계약이 docstring 에 명시되어야 한다.
        doc = Order.__doc__
        self.assertIn("is_billed", doc)
        self.assertIn("sync", doc)

    def test_no_tuition_charge_model(self):
        # 헤더 노트 ②(2026-07-15 미결 해소): 동보 수강료 없음 →
        # tuition_charges 표 삭제. 구현 금지(PRD 3.2.3 과금 없음).
        self.assertFalse(hasattr(payments_models, "TuitionCharge"))


class PaymentTests(TestCase):
    def setUp(self):
        self.order = Order.objects.create(
            student=make_student(), product=make_product(), amount=45000
        )

    def test_table_and_pk_column_follow_design(self):
        self.assertEqual(Payment._meta.db_table, "payments")
        self.assertEqual(Payment._meta.pk.column, "payment_id")

    def test_status_value_set_follows_design(self):
        # baseline: 대기/완료/실패/취소
        self.assertEqual(set(Payment.Status.values), {"대기", "완료", "실패", "취소"})

    def test_provider_is_value_not_schema(self):
        # key_considerations §4: Provider 추상화 — 업체 교체는 값 교체로 끝난다.
        # 결제선생은 값집합의 한 값일 뿐, 업체 종속 컬럼은 없다(외부 참조는
        # 중립 컬럼 external_ref 하나).
        self.assertIn("결제선생", Payment.Provider.values)
        field_names = {f.name for f in Payment._meta.get_fields()}
        self.assertIn("external_ref", field_names)
        self.assertFalse(
            {"payssam_id", "payssam_ref", "pg_tid"} & field_names,
            "업체 종속 컬럼 금지(Provider 중립)",
        )

    def test_provider_abstraction_contract_documented(self):
        self.assertIn("Provider", Payment.__doc__)

    def test_payment_records_transaction(self):
        payment = Payment.objects.create(
            order=self.order,
            provider=Payment.Provider.PAYSSAM,
            status=Payment.Status.COMPLETED,
            amount=45000,
        )
        self.assertEqual(self.order.payments.get(), payment)
        self.assertIsNone(payment.external_ref)
        self.assertIsNone(payment.paid_at)
        self.assertIsNone(payment.synced_at)

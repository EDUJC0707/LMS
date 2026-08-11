"""payments 도메인 — 교재 결제 (DB 설계 도메인 5).

정렬 테이블(docs/db/lms-db-design-2026-07-15.md 도메인 5 + 헤더 노트 ②,
baseline lms-db-spec.html Domain 5, PRD 3.1.5/3.2.5):
  - products   교재/상품
  - orders     주문·청구(학생·학부모 양측 결제, sync·중복 방지 부분 UQ)
  - payments   결제 트랜잭션(Provider 추상화 — 결제선생↔PG 값 교체)

`tuition_charges` 는 만들지 않는다 — 헤더 노트 ②(2026-07-15 미결 해소):
동보 추가 과금 없음(PRD 3.2.3). 과금은 커리큘럼(약 10주) 교재 1회
결제뿐이다.

그린필드이므로 baseline+delta 의 최종 상태로 바로 구현한다.
인덱스는 설계 §4.7 기준(tuition 인덱스는 표 삭제로 함께 소멸).
"""
from django.db import models


class Product(models.Model):
    """`products` — 교재/상품 마스터 (baseline 도메인 5, PRD 3.1.5).

    유일한 과금 대상(교재 1회 결제). 판매 종료는 is_active=false
    (soft-off) — 주문 이력이 참조하므로 실삭제 차단(Order.product PROTECT).
    """

    product_id = models.BigAutoField(primary_key=True)
    name = models.CharField("교재명", max_length=200)
    price = models.IntegerField("가격(원)")
    is_active = models.BooleanField("판매 여부", default=True)
    created_at = models.DateTimeField("생성 시각", auto_now_add=True)

    class Meta:
        db_table = "products"
        verbose_name = "교재"
        verbose_name_plural = "교재"

    def __str__(self):
        return self.name


class Order(models.Model):
    """`orders` — 교재 주문·청구 (baseline + delta, PRD 3.1.5/3.2.5).

    **양측 결제 + 중복 방지(sync) 계약**:
    - 학생·학부모 어느 쪽이든 결제를 개시할 수 있다(initiated_by_user 가
      개시 계정, billed_to_parent 가 청구 대상 학부모).
    - **부분 UQ**(student, product) WHERE status <> `취소` — 동일 학생·동일
      교재의 활성 청구는 어느 경로로든 1건만 성립(DB 강제 지점). 취소 건은
      제외되어 재청구 가능.
    - **is_billed** = 청구서(결제선생) 발송 여부 플래그. 어느 경로에서
      요청이 와도 이 플래그가 true 면 중복 발송하지 않는다(양측 sync 판정
      근거 — 발송 전 확인은 앱 레이어, 유일성은 부분 UQ 가 백스톱).
    - charge_trigger: 청구는 `첫수업`(해당 교재가 쓰이는 첫 수업 기준 1회,
      source_session 이 근거 회차) 또는 `수동` — 주차 반복 청구 아님.
    - 결제선생 동기화 상태는 payments(트랜잭션)로 반영하고, 주문 status
      (미결제→결제완료→배부완료)는 그 결과의 요약 상태다.
    - amount 는 주문 시점 가격 스냅샷(교재 가격 변경과 분리).
    - billed_to_phone: 청구서 발송 학부모 연락처 스냅샷(baseline 유지 —
      계정 없는 학부모 연락처 대응).
    """

    class Status(models.TextChoices):
        UNPAID = "미결제", "미결제"
        PAID = "결제완료", "결제완료"
        DELIVERED = "배부완료", "배부완료"
        CANCELLED = "취소", "취소"

    class ChargeTrigger(models.TextChoices):
        FIRST_SESSION = "첫수업", "첫수업"
        MANUAL = "수동", "수동"

    order_id = models.BigAutoField(primary_key=True)
    student = models.ForeignKey(
        "accounts.Student",
        on_delete=models.PROTECT,
        db_column="student_id",
        related_name="orders",
        verbose_name="구매 학생",
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        db_column="product_id",
        related_name="orders",
        verbose_name="교재",
    )
    amount = models.IntegerField("청구 금액(원)")
    status = models.CharField(
        "상태", max_length=15, choices=Status.choices, default=Status.UNPAID
    )
    billed_to_phone = models.CharField("청구 연락처", max_length=20, null=True, blank=True)  # noqa: DJ001
    ordered_at = models.DateTimeField("청구 시각", auto_now_add=True)
    paid_at = models.DateTimeField("결제완료 시각", null=True, blank=True)
    delivered_at = models.DateTimeField("배부완료 시각", null=True, blank=True)
    initiated_by_user = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="initiated_by_user_id",
        related_name="initiated_orders",
        verbose_name="결제 개시자",
    )
    billed_to_parent = models.ForeignKey(
        "accounts.Parent",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="billed_to_parent_id",
        related_name="billed_orders",
        verbose_name="청구 대상 학부모",
    )
    is_billed = models.BooleanField("청구서 발송 여부", default=False)
    billed_at = models.DateTimeField("청구 발송 시각", null=True, blank=True)
    # 발송된 청구서의 결제 링크. **업체 종속 컬럼이 아니다** — 어느 제공자든
    # 결제 페이지 URL 을 돌려주므로 중립 값이다(Provider 계약).
    # 여기 남겨 두는 이유: PRD 3.2.5 임베드가 이 주소를 열고, 3.1.5 중복 차단이
    # 재발송을 막으므로 두 번째 클릭에 돌려줄 URL 이 DB 에 없으면 학생이 자기
    # 청구서로 되돌아갈 방법이 사라진다(업체 조회 API 는 이 URL 을 안 준다).
    pay_url = models.URLField("결제 링크", max_length=500, null=True, blank=True)  # noqa: DJ001
    charge_trigger = models.CharField(  # noqa: DJ001
        "청구 트리거", max_length=15, choices=ChargeTrigger.choices, null=True, blank=True
    )
    source_session = models.ForeignKey(
        "grades.ClassSession",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="source_session_id",
        related_name="triggered_orders",
        verbose_name="첫 수업 근거 회차",
    )

    class Meta:
        db_table = "orders"
        verbose_name = "주문"
        verbose_name_plural = "주문"
        constraints = [
            # 설계 §4.7: 활성 청구 유일성(학생×교재) — 중복청구·양측 sync 근거
            models.UniqueConstraint(
                fields=["student", "product"],
                condition=~models.Q(status="취소"),
                name="uq_orders_active",
            ),
        ]
        indexes = [
            # 설계 §4.7: 상태별 조회(완료·미결제·배부 관리 화면)
            models.Index(fields=["status"], name="idx_orders_status"),
        ]

    def __str__(self):
        return f"주문 학생{self.student_id} 교재{self.product_id}({self.status})"


class Payment(models.Model):
    """`payments` — 결제 트랜잭션 (baseline 도메인 5, PRD 3.1.5/6-5).

    **Provider 추상화 계약(key_considerations §4)**: 결제 로직은 앱 레이어의
    Provider 인터페이스로 감싸고, DB 는 provider 값과 중립 외부 참조
    (external_ref)만 저장한다. 결제선생 → PG 전환 시 값집합에 값을 추가하고
    구현체만 교체(업체 종속 컬럼 금지 — 스키마 불변).
    - 결제선생 데이터 동기화가 이 표를 채운다(synced_at = 동기화 시각).
      주문 상태 요약(orders.status)의 근거.
    """

    class Provider(models.TextChoices):
        PAYSSAM = "결제선생", "결제선생"

    class Status(models.TextChoices):
        PENDING = "대기", "대기"
        COMPLETED = "완료", "완료"
        FAILED = "실패", "실패"
        CANCELLED = "취소", "취소"

    payment_id = models.BigAutoField(primary_key=True)
    order = models.ForeignKey(
        Order,
        on_delete=models.PROTECT,
        db_column="order_id",
        related_name="payments",
        verbose_name="주문",
    )
    provider = models.CharField("결제 제공자", max_length=20, choices=Provider.choices)
    external_ref = models.CharField(  # noqa: DJ001
        "외부 결제 참조 ID", max_length=100, null=True, blank=True
    )
    status = models.CharField("상태", max_length=15, choices=Status.choices)
    amount = models.IntegerField("결제 금액(원)")
    paid_at = models.DateTimeField("결제 시각", null=True, blank=True)
    synced_at = models.DateTimeField("동기화 시각", null=True, blank=True)
    created_at = models.DateTimeField("생성 시각", auto_now_add=True)

    class Meta:
        db_table = "payments"
        verbose_name = "결제"
        verbose_name_plural = "결제"

    def __str__(self):
        return f"결제 주문{self.order_id} {self.amount}원({self.status})"

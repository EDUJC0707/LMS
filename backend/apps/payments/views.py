"""payments 뷰 — 교재 결제 조회 (PRD 3.1.5·3.2.5·3.4).

- GET /api/student/payments              내 교재 주문·결제 상태 (IsStudent)
- GET /api/parent/payments[?student_id=] 자녀 결제 상태 (IsParent, 읽기 전용)
- GET /api/admin/payments                학생별 결제·배부 상태 (기능 키 `결제확인`)

**소유 판정이 이 파일의 일 전부다.** 목록 조립은 `consumer.build_order_list`
가 하고, 여기서는 "이 요청자가 어느 학생을 볼 수 있는가"만 정한다. 그 판정이
느슨하면 번호만 알면 남의 결제 내역이 열린다(2026-08-04 영상 트랙 사고 —
관리 쪽이 다 서 있는데 소비를 막는 코드가 없었다).
"""
import logging

from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.features import FeatureKey
from apps.accounts.models import Parent, ParentStudent, Student
from apps.accounts.permissions import FeatureRequired, IsOwner, IsParent, IsStudent

from . import billing, consumer, payment_admin, sync
from .models import Order, Product
from .provider import PaymentError, TemporaryPaymentError, get_adapter

logger = logging.getLogger(__name__)

_NOT_FOUND_MESSAGE = "찾을 수 없습니다."


def _resolve_product(request):
    """요청의 product_id → 판매 중인 교재. 없거나 판매 종료면 (None, 404 응답).

    판매 종료(is_active=false)와 없는 번호를 **같은 404** 로 답한다 — 갈리면
    "그 번호의 교재는 존재한다"가 새어 나간다(§4 상태 기반 노출).
    """
    raw = request.data.get("product_id")
    try:
        product_id = int(raw)
    except (TypeError, ValueError):
        return None, Response(
            {"detail": "product_id가 올바르지 않습니다."}, status=status.HTTP_400_BAD_REQUEST
        )
    product = Product.objects.filter(product_id=product_id, is_active=True).first()
    if product is None:
        return None, Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)
    return product, None


def _bill(request, student, product, parent=None):
    """청구 개시 공통 응답 — 학생·학부모 경로가 같은 판정을 쓴다.

    업체 실패는 **재시도 가능 여부로 상태 코드가 갈린다**: 일시 오류는 503
    (잠시 뒤 다시), 영구 오류는 502(사람이 손대야 풀린다 — 포인트 부족·키
    문제). 하나로 뭉치면 화면이 "다시 시도" 를 무한히 권한다.

    **업체 사유는 로그로만 간다.** 잔액이 마르면 업체는 `POINT_001`
    ("포인트가 부족합니다")로 거절하는데, 그 문장을 학생에게 그대로 보이면
    ① 학생은 무슨 말인지 알 수 없고 ② 정작 충전해야 하는 관리자는 그 사실을
    영영 모른다. 자동충전을 안 켜기로 했으므로(2026-08-11 결정) 사람이 알아야
    풀리는 종류의 실패다 — 로그가 그 유일한 통로다.
    """
    try:
        order, created = billing.start_billing(
            student, product, actor=request.user, parent=parent
        )
    except billing.BillingError as exc:
        # 우리 쪽 사유(연락처 없음 등)는 사용자가 고칠 수 있는 말이라 그대로 보인다.
        return Response({"detail": exc.message}, status=status.HTTP_400_BAD_REQUEST)
    except TemporaryPaymentError as exc:
        logger.warning("청구서 발송 일시 실패 (student=%s): %s", student.student_id, exc)
        return Response(
            {"detail": "청구서를 보내지 못했습니다. 잠시 후 다시 시도해 주세요."},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    except PaymentError as exc:
        logger.error("청구서 발송 실패 (student=%s): %s", student.student_id, exc)
        return Response(
            {"detail": "청구서를 보내지 못했습니다."},
            status=status.HTTP_502_BAD_GATEWAY,
        )
    return Response(
        {"order_id": order.order_id, "pay_url": order.pay_url, "status": order.status},
        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
    )


def _my_student(request):
    """로그인 학생의 students 행. 없으면 None(예외 상태 — 닫힘 방어)."""
    return Student.objects.filter(user=request.user).first()


def _resolve_child(request):
    """학부모의 대상 자녀 결정 — (student, error_response).

    parent_students 에 연결된 자녀만 조회 가능. **소유 밖 student_id 는 존재
    여부와 무관하게 404** — 타인 자녀의 존재를 노출하지 않는다(§4 상태 기반
    노출). student_id 생략 시 첫 자녀(student_id 오름차순 — /api/me children
    드롭다운 순서). grades·curriculum 의 같은 이름 헬퍼와 같은 판정이다.
    """
    # 조회는 쿼리스트링(GET), 청구 개시는 본문(POST)으로 자녀를 고른다. 한쪽만
    # 보면 POST 경로에서 지정이 조용히 무시되고 **첫 자녀로 떨어진다** — 소유
    # 밖 자녀를 막으려던 검사가 통과해 버린다.
    raw_student_id = request.query_params.get("student_id")
    if raw_student_id is None and isinstance(getattr(request, "data", None), dict):
        raw_student_id = request.data.get("student_id")
    student_id = None
    if raw_student_id:
        try:
            student_id = int(raw_student_id)
        except ValueError:
            return None, Response(
                {"detail": "student_id가 올바르지 않습니다."},
                status=status.HTTP_400_BAD_REQUEST,
            )
    parent = Parent.objects.filter(user=request.user).first()
    if parent is None:
        return None, Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)
    links = list(
        ParentStudent.objects.filter(parent=parent)
        .select_related("student")
        .order_by("student_id")
    )
    if student_id is None:
        student = links[0].student if links else None
    else:
        student = next((link.student for link in links if link.student_id == student_id), None)
    if student is None:
        return None, Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)
    return student, None


class StudentPaymentListView(APIView):
    """GET /api/student/payments — 내 교재 주문·결제 상태."""

    permission_classes = [IsStudent]

    def get(self, request):
        student = _my_student(request)
        if student is None:
            # 학생 role 인데 students 행이 없는 예외 상태. 500 을 내는 대신
            # 빈 목록이다 — 볼 주문이 없는 것이 사실이고 화면은 그대로 선다.
            return Response([])
        return Response(consumer.build_order_list(student))


class ParentPaymentListView(APIView):
    """GET /api/parent/payments?student_id= — 자녀 교재 결제 상태(읽기 전용)."""

    permission_classes = [IsParent]

    def get(self, request):
        student, error = _resolve_child(request)
        if error is not None:
            return error
        return Response(consumer.build_order_list(student))


class ProductListView(APIView):
    """GET /api/payments/products — 살 수 있는 교재 목록(PRD 3.2.5, FLOW 1-6).

    청구 개시가 `product_id` 를 받는데 그 번호를 소비자에게 알려 주는 자리가
    없었다 — 목록이 없으면 구매 버튼을 그릴 자리 자체가 없다(videos 목록 선례).

    **목록은 학생마다 다르다.** 교재는 커리에 붙으므로(FLOW 1-6) 자기가 듣는
    커리의 것만 본다. 학부모는 자녀를 고르고(`student_id`) 그 자녀의 목록을
    본다 — 자녀마다 커리가 다르면 목록도 다르다.
    이미 산 것을 걸러 내지 않는다 — 화면이 자기 주문 목록과 맞춰 본다.
    """

    permission_classes = [IsStudent | IsParent]

    def get(self, request):
        if IsParent().has_permission(request, self):
            student, error = _resolve_child(request)
            if error is not None:
                return error
        else:
            student = _my_student(request)
            if student is None:
                return Response([])
        return Response(consumer.purchasable_products(student))


class StudentBillView(APIView):
    """POST /api/student/payments/bill — 버튼 클릭 한 번으로 청구 개시(PRD 3.1.5)."""

    permission_classes = [IsStudent]

    def post(self, request):
        student = _my_student(request)
        if student is None:
            return Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)
        product, error = _resolve_product(request)
        if error is not None:
            return error
        return _bill(request, student, product)


class ParentBillView(APIView):
    """POST /api/parent/payments/bill — 학부모 경로의 청구 개시(양측 결제).

    학생이 이미 눌렀으면 다시 보내지 않는다 — 중복 차단은 경로가 아니라
    학생·교재 짝으로 판정한다(billing.start_billing).
    """

    permission_classes = [IsParent]

    def post(self, request):
        student, error = _resolve_child(request)
        if error is not None:
            return error
        product, error = _resolve_product(request)
        if error is not None:
            return error
        parent = Parent.objects.filter(user=request.user).first()
        return _bill(request, student, product, parent=parent)


class AdminBillView(APIView):
    """POST /api/admin/payments/bill — 관리자가 청구를 시작한다(FLOW 2-4·2-5).

    이 자리가 없어서 **조교는 청구를 시작할 수 없었다** — `start_billing` 을
    부르는 곳이 학생·학부모 뷰뿐이었다. FLOW 2-4 는 계정 발급과 함께 결제가
    나간다고 정했고 2-5 는 언제든 다시 보낼 수 있어야 한다고 정했다.

    게이트는 기능 키 `결제확인` 이다 — 배부 처리와 같은 축(일상 운영)이고,
    조교 프리셋에는 없으므로 기본 차단이다(key_considerations §2). 돈이
    되돌아가는 취소·환불만 대표 전용(IsOwner)으로 따로 잠겨 있다.

    **청구서는 학부모에게 간다**(FLOW 2-4). 연결된 학부모가 없으면 학생 본인
    번호로 떨어진다 — 번호가 아예 없으면 `start_billing` 이 막는다.
    결제선생을 쓰지 않는 반(FLOW 2-7)도 거기서 막힌다.
    """

    permission_classes = [FeatureRequired(FeatureKey.PAYMENT_CHECK)]

    def post(self, request):
        student_id = request.data.get("student_id")
        student = Student.objects.filter(pk=student_id).select_related("user").first()
        if student is None:
            return Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)
        product, error = _resolve_product(request)
        if error is not None:
            return error
        link = (
            ParentStudent.objects.filter(student=student)
            .select_related("parent")
            .order_by("parent_id")
            .first()
        )
        return _bill(request, student, product, parent=link.parent if link else None)


class PaymentCallbackView(APIView):
    """POST /api/payments/callback — 업체 결제 승인 통지(PRD 3.1.5 동기화).

    **인증이 없다.** 업체 서버가 부르므로 세션이 없고, 업체 문서에 서명·검증
    수단도 없다(2026-08-05 조사). 그래서 **본문을 신뢰하지 않는다** — 여기서
    하는 일은 "그 청구 번호를 다시 확인하라"는 신호를 받는 것뿐이고, 상태는
    `sync.sync_order` 가 업체에게 되물어 확정한다. 본문을 그대로 반영하면
    아무나 billId 를 찍어 결제를 완료로 만들 수 있다.

    응답 계약은 업체가 정한다 — 수신 성공은 `{"code": "0000"}` 이다.
    **처리하지 못한 것을 0000 으로 삼키지 않는다**: 모르는 청구 번호나 업체
    조회 실패를 성공으로 답하면 장부가 어긋난 사실이 그대로 사라진다.
    (재전달 정책은 업체 문서에 없다 — 확인 대기 중.)
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        bill_ref = (request.data or {}).get("billId")
        if not bill_ref:
            return Response({"code": "9001", "msg": "billId가 없습니다."})
        try:
            sync.sync_order(bill_ref)
        except sync.UnknownBill:
            logger.error("결제 콜백: 모르는 청구 번호입니다 (billId=%s)", bill_ref)
            return Response({"code": "9002", "msg": "청구서를 찾을 수 없습니다."})
        except PaymentError as exc:
            # 확인을 못 했으므로 성공으로 답하지 않는다 — 다시 보내 주는 것이 낫다.
            logger.warning("결제 콜백: 상태 확인 실패 (billId=%s): %s", bill_ref, exc)
            return Response({"code": "9003", "msg": "상태를 확인하지 못했습니다."})
        return Response({"code": "0000", "msg": "Success"})


class AdminPaymentListView(APIView):
    """GET /api/admin/payments — 학생별 교재 구매·결제·배부 상태(PRD 3.1.5).

    게이트는 기능 키 `결제확인` 이다. 조교 프리셋에는 없으므로 기본 차단이고,
    대표가 delta 로만 연다(key_considerations §2).
    """

    permission_classes = [FeatureRequired(FeatureKey.PAYMENT_CHECK)]

    def get(self, request):
        try:
            queryset = payment_admin.build_queryset(request.query_params)
        except payment_admin.PaymentQueryError as exc:
            return Response({"detail": exc.message}, status=status.HTTP_400_BAD_REQUEST)
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        return paginator.get_paginated_response(
            [payment_admin.build_row(order) for order in page]
        )


def _order_or_404(order_id):
    return Order.objects.select_related("student__user", "product").filter(pk=order_id).first()


class AdminPaymentCancelView(APIView):
    """POST /api/admin/payments/{order_id}/cancel — 취소·환불(PRD 3.1.5).

    **대표 전용이다.** 돈이 되돌아가는 파괴적 조작이라 기능 키가 아니라 역할
    게이트로 잠근다(key_considerations §2 가 대표 전용 후보로 꼽아 둔 항목,
    §5 "파괴적 작업은 관리자 수동 + 이력"). `결제확인` 을 delta 로 받은
    관리자도 여기는 못 연다 — 권한 매트릭스(IsOwner) 와 같은 축이다.
    """

    permission_classes = [IsOwner]

    def post(self, request, order_id):
        order = _order_or_404(order_id)
        if order is None:
            return Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)
        try:
            order = payment_admin.cancel_order(order, reason=request.data.get("reason"))
        except payment_admin.PaymentQueryError as exc:
            return Response({"detail": exc.message}, status=status.HTTP_400_BAD_REQUEST)
        except TemporaryPaymentError as exc:
            logger.warning("결제 취소 일시 실패 (order=%s): %s", order_id, exc)
            return Response(
                {"detail": "취소하지 못했습니다. 잠시 후 다시 시도해 주세요."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except PaymentError as exc:
            logger.error("결제 취소 실패 (order=%s): %s", order_id, exc)
            return Response(
                {"detail": "취소하지 못했습니다."}, status=status.HTTP_502_BAD_GATEWAY
            )
        return Response(payment_admin.build_row(order))


class AdminPaymentDeliverView(APIView):
    """POST /api/admin/payments/{order_id}/deliver — 배부완료 처리(PRD 3.1.5).

    취소와 달리 **일상 운영**이라 기능 키(`결제확인`)로 연다.
    """

    permission_classes = [FeatureRequired(FeatureKey.PAYMENT_CHECK)]

    def post(self, request, order_id):
        order = _order_or_404(order_id)
        if order is None:
            return Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)
        try:
            order = payment_admin.mark_delivered(order)
        except payment_admin.PaymentQueryError as exc:
            return Response({"detail": exc.message}, status=status.HTTP_400_BAD_REQUEST)
        return Response(payment_admin.build_row(order))


class AdminPaymentBalanceView(APIView):
    """GET /api/admin/payments/balance — 선불 잔액(쌤포인트).

    **자동충전을 안 켜기로 했으므로**(2026-08-11) 사람이 보는 자리가 있어야
    한다. 잔액이 마르면 청구가 통째로 멈추는데 지금은 로그 말고 알 길이 없다.

    조회 실패를 500 으로 올리지 않는다 — 잔액을 못 읽는 것과 결제 화면이
    통째로 죽는 것은 다른 일이다. `balance: null` 로 내리고 화면이 그 자리만 비운다.
    """

    permission_classes = [FeatureRequired(FeatureKey.PAYMENT_CHECK)]

    def get(self, request):
        try:
            balance = get_adapter().read_balance()
        except PaymentError as exc:
            logger.warning("잔액 조회 실패: %s", exc)
            return Response({"balance": None, "charge_url": None})
        if balance is None:
            return Response({"balance": None, "charge_url": None})
        return Response({"balance": balance.amount, "charge_url": balance.charge_url})

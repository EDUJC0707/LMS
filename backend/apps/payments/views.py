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
from apps.accounts.permissions import FeatureRequired, IsParent, IsStudent

from . import billing, consumer, payment_admin, sync
from .models import Product
from .provider import PaymentError, TemporaryPaymentError

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
    """
    try:
        order, created = billing.start_billing(
            student, product, actor=request.user, parent=parent
        )
    except billing.BillingError as exc:
        return Response({"detail": exc.message}, status=status.HTTP_400_BAD_REQUEST)
    except TemporaryPaymentError as exc:
        return Response(
            {"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE
        )
    except PaymentError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
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

"""payments 뷰 — 교재 결제 조회 (PRD 3.1.5·3.2.5·3.4).

- GET /api/student/payments              내 교재 주문·결제 상태 (IsStudent)
- GET /api/parent/payments[?student_id=] 자녀 결제 상태 (IsParent, 읽기 전용)
- GET /api/admin/payments                학생별 결제·배부 상태 (기능 키 `결제확인`)

**소유 판정이 이 파일의 일 전부다.** 목록 조립은 `consumer.build_order_list`
가 하고, 여기서는 "이 요청자가 어느 학생을 볼 수 있는가"만 정한다. 그 판정이
느슨하면 번호만 알면 남의 결제 내역이 열린다(2026-08-04 영상 트랙 사고 —
관리 쪽이 다 서 있는데 소비를 막는 코드가 없었다).
"""
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.features import FeatureKey
from apps.accounts.models import Parent, ParentStudent, Student
from apps.accounts.permissions import FeatureRequired, IsParent, IsStudent

from . import consumer, payment_admin

_NOT_FOUND_MESSAGE = "찾을 수 없습니다."


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
    raw_student_id = request.query_params.get("student_id")
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

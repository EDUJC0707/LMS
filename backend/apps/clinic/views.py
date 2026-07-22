"""clinic 뷰 — 클리닉 신청 API 4차 슬라이스 (PRD 3.2.4·§4).

- GET   /api/student/clinic?exam_id=          자격·슬롯 잔여·내 신청 (IsStudent)
- POST  /api/student/clinic/requests          신청 생성 (자격·정원·마감·노쇼·중복)
- PATCH /api/student/clinic/requests/{id}     시간 변경 (같은 규칙 재검증)
- POST  /api/student/clinic/requests/{id}/cancel  취소 (노쇼 미집계)

규칙 강제·페이로드 조립은 booking 서비스가 담당한다 — 뷰는 역할 게이트·
입력 형태 검증·대상 조회(본인 것만 — 소유 밖은 404 존재 비노출)·상태 코드
매핑만 한다(2차 슬라이스 home 선례).
"""
import datetime

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Student
from apps.accounts.permissions import IsStudent
from apps.grades.models import Exam

from . import booking
from .models import ClinicRequest, ClinicSlot

_NOT_FOUND_MESSAGE = "찾을 수 없습니다."


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _load_student(request):
    """학생 role 인데 students 행이 없는 예외 상태는 닫힘(404)으로 방어."""
    return Student.objects.filter(user=request.user).first()


def _parse_date(raw):
    """ISO 날짜 문자열 → date. 오류는 None(뷰가 400 처리)."""
    if not isinstance(raw, str):
        return None
    try:
        return datetime.date.fromisoformat(raw)
    except ValueError:
        return None


class StudentClinicView(APIView):
    """GET /api/student/clinic?exam_id= — 자격·슬롯·내 신청 현황."""

    permission_classes = [IsStudent]

    def get(self, request):
        student = _load_student(request)
        if student is None:
            return Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)
        raw_exam_id = request.query_params.get("exam_id")
        try:
            exam_id = int(raw_exam_id)
        except (TypeError, ValueError):
            return Response(
                {"detail": "exam_id가 필요합니다."}, status=status.HTTP_400_BAD_REQUEST
            )
        exam = Exam.objects.filter(pk=exam_id).first()
        if exam is None:
            return Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)
        return Response(booking.build_clinic_home(student, exam))


class ClinicRequestCreateView(APIView):
    """POST /api/student/clinic/requests — 신청 생성."""

    permission_classes = [IsStudent]

    def post(self, request):
        student = _load_student(request)
        if student is None:
            return Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)
        body = request.data if isinstance(request.data, dict) else {}
        exam_id = body.get("exam_id")
        slot_id = body.get("slot_id")
        requested_date = _parse_date(body.get("requested_date"))
        if not _is_int(exam_id) or not _is_int(slot_id) or requested_date is None:
            return Response(
                {"detail": "exam_id·slot_id·requested_date(YYYY-MM-DD)가 필요합니다."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        exam = Exam.objects.filter(pk=exam_id).first()
        if exam is None:
            return Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)
        # 폐지(soft-off) 슬롯은 신청 대상이 아니다 — 존재 비노출(404)
        slot = ClinicSlot.objects.filter(pk=slot_id, is_active=True).first()
        if slot is None:
            return Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)
        try:
            clinic_request, now = booking.create_booking(
                student=student, exam=exam, slot=slot, requested_date=requested_date
            )
        except booking.ClinicError as error:
            return Response({"detail": error.message}, status=error.http_status)
        return Response(
            _booking_payload(clinic_request, now), status=status.HTTP_201_CREATED
        )


class ClinicRequestChangeView(APIView):
    """PATCH /api/student/clinic/requests/{id} — 시간 변경(같은 규칙 재검증)."""

    permission_classes = [IsStudent]

    def patch(self, request, clinic_id):
        student = _load_student(request)
        if student is None:
            return Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)
        clinic_request = (
            ClinicRequest.objects.select_related("slot", "student", "exam")
            .filter(pk=clinic_id, student=student)  # 본인 것만 — 소유 밖 404
            .first()
        )
        if clinic_request is None:
            return Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)
        body = request.data if isinstance(request.data, dict) else {}
        if "slot_id" not in body and "requested_date" not in body:
            return Response(
                {"detail": "slot_id 또는 requested_date가 필요합니다."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        slot = clinic_request.slot
        if "slot_id" in body:
            if not _is_int(body["slot_id"]):
                return Response(
                    {"detail": "slot_id가 올바르지 않습니다."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            slot = ClinicSlot.objects.filter(pk=body["slot_id"], is_active=True).first()
        if slot is None:
            return Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)
        requested_date = clinic_request.requested_date
        if "requested_date" in body:
            requested_date = _parse_date(body["requested_date"])
            if requested_date is None:
                return Response(
                    {"detail": "requested_date 형식은 YYYY-MM-DD 입니다."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        try:
            clinic_request, now = booking.change_booking(clinic_request, slot, requested_date)
        except booking.ClinicError as error:
            return Response({"detail": error.message}, status=error.http_status)
        return Response(_booking_payload(clinic_request, now))


class ClinicRequestCancelView(APIView):
    """POST /api/student/clinic/requests/{id}/cancel — 취소(노쇼 미집계)."""

    permission_classes = [IsStudent]

    def post(self, request, clinic_id):
        student = _load_student(request)
        if student is None:
            return Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)
        clinic_request = (
            ClinicRequest.objects.select_related("slot")
            .filter(pk=clinic_id, student=student)
            .first()
        )
        if clinic_request is None:
            return Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)
        try:
            clinic_request, now = booking.cancel_booking(clinic_request)
        except booking.ClinicError as error:
            return Response({"detail": error.message}, status=error.http_status)
        return Response({"request": booking.request_block(clinic_request, now)})


def _booking_payload(clinic_request, now):
    """신청·변경 응답 — 신청 반영 후 잔여 정원 포함(재조회 불필요 계약)."""
    slot = clinic_request.slot
    taken = booking.active_count(slot, clinic_request.requested_date)
    return {
        "request": booking.request_block(clinic_request, now),
        "slot": booking.slot_block(slot, clinic_request.requested_date, taken),
    }

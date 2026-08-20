"""clinic 뷰 — 클리닉 신청 4차 + 클리닉 관리자 8차 슬라이스 (PRD 3.2.4·§4).

4차(소비자 — consumer_urls.py):
- GET   /api/student/clinic?exam_id=          자격·내 신청 현황 (IsStudent)
- GET   /api/student/clinic/availability      날짜별 가용 시간 (IsStudent, 자격 403)
- POST  /api/student/clinic/requests          신청 생성 (자격·정원·마감·노쇼·중복)
- PATCH /api/student/clinic/requests/{id}     시간 변경 (같은 규칙 재검증)
- POST  /api/student/clinic/requests/{id}/cancel  취소 (노쇼 미집계)

8차(관리자 — admin_urls.py):
- GET  /api/admin/clinic/requests?status=&date=      대기열 (클리닉배정)
- POST /api/admin/clinic/requests/{id}/assign        승인+배정 (클리닉배정)
- POST /api/admin/clinic/requests/{id}/reject        미승인 (클리닉배정) {reason}
- POST /api/admin/clinic/requests/{id}/attendance    출결 처리·노쇼 (클리닉배정)
- POST /api/admin/clinic/requests/{id}/evaluation    평가 기록 (클리닉배정)
- GET  /api/admin/clinic/eval-criteria               평가 항목 (클리닉배정)
- POST /api/admin/clinic/students/{id}/unban         제한 해제 (**대표 전용**)

규칙 강제·페이로드 조립은 booking(소비자)·clinic_admin(관리자) 서비스가
담당한다 — 뷰는 역할·기능 키 게이트, 입력 형태 검증, 대상 조회(소비자는
본인 것만 — 소유 밖은 404 존재 비노출), 상태 코드 매핑만 한다.
"""
import datetime

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.features import FeatureKey
from apps.accounts.models import Student, User
from apps.accounts.permissions import FeatureRequired, IsOwner, IsStudent
from apps.grades.models import Exam

from . import booking, clinic_admin
from .models import ClinicEvalCriteria, ClinicEvaluationItem, ClinicRequest, ClinicSlot

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


class StudentClinicAvailabilityView(APIView):
    """GET /api/student/clinic/availability?exam_id=&from=&to= — 날짜별 가용 시간.

    달력에서 날짜를 고르고 그 날의 시간 하나를 선택하는 흐름(Calendly 형)의
    데이터 원천. 자격·구간 판정과 노출 규칙은 booking.availability 계약.
    """

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
        bounds = {}
        for key, param in (("date_from", "from"), ("date_to", "to")):
            raw = request.query_params.get(param)
            if raw is None:
                continue
            parsed = _parse_date(raw)
            if parsed is None:
                return Response(
                    {"detail": f"{param} 형식은 YYYY-MM-DD 입니다."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            bounds[key] = parsed
        exam = Exam.objects.filter(pk=exam_id).first()
        if exam is None:
            return Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)
        try:
            payload = booking.availability(student, exam, **bounds)
        except booking.ClinicError as error:
            return Response({"detail": error.message}, status=error.http_status)
        return Response(payload)


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
    """신청·변경 응답 — 확정된 슬롯 요약 동봉(재조회 불필요 계약).

    잔여 정원은 싣지 않는다 — 정원 1 고정이라 신청이 성공한 시점에 그
    날짜·시간은 항상 마감이다(booking.slot_block).
    """
    return {
        "request": booking.request_block(clinic_request, now),
        "slot": booking.slot_block(clinic_request.slot),
    }


# --- 관리자(8차) ----------------------------------------------------------


def _load_clinic_request(clinic_id):
    return (
        ClinicRequest.objects.select_related("student__user", "assigned_staff")
        .filter(pk=clinic_id)
        .first()
    )


class AdminClinicQueueView(APIView):
    """GET /api/admin/clinic/requests?status=&date= — 신청 대기열."""

    permission_classes = [FeatureRequired(FeatureKey.CLINIC_ASSIGN)]

    def get(self, request):
        status_filter = request.query_params.get("status")
        if status_filter and status_filter not in ClinicRequest.Status.values:
            return Response(
                {"detail": "status 값이 올바르지 않습니다."}, status=status.HTTP_400_BAD_REQUEST
            )
        date_filter = None
        raw_date = request.query_params.get("date")
        if raw_date:
            date_filter = _parse_date(raw_date)
            if date_filter is None:
                return Response(
                    {"detail": "date 형식은 YYYY-MM-DD 입니다."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        period = request.query_params.get("period")
        if period and period not in clinic_admin.PERIODS:
            return Response(
                {"detail": "period 값이 올바르지 않습니다."}, status=status.HTTP_400_BAD_REQUEST
            )
        return Response(
            {"requests": clinic_admin.queue_rows(status_filter, date_filter, period)}
        )


class AdminClinicAssignView(APIView):
    """POST /api/admin/clinic/requests/{id}/assign — 승인+배정(재배정 허용)."""

    permission_classes = [FeatureRequired(FeatureKey.CLINIC_ASSIGN)]

    def post(self, request, clinic_id):
        clinic_request = _load_clinic_request(clinic_id)
        if clinic_request is None:
            return Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)
        body = request.data if isinstance(request.data, dict) else {}
        staff_id = body.get("assigned_staff_id")
        if not _is_int(staff_id):
            return Response(
                {"detail": "assigned_staff_id가 필요합니다."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # 링크는 **서버가 만든다**. 관리자가 손으로 넣는 경로는 없앴다
        # (2026-08-18) — 실제로 그렇게 배정하는 상황이 없는데 코드 경로만
        # 하나 더 있었다. 만들지 못하면 배정도 성립하지 않는다(assign 이 막는다).
        staff_user = User.objects.filter(pk=staff_id).first()
        try:
            clinic_admin.assign(clinic_request, staff_user)
        except booking.ClinicError as error:
            return Response({"detail": error.message}, status=error.http_status)
        return Response(clinic_admin.queue_row(clinic_request))


class AdminClinicRejectView(APIView):
    """POST /api/admin/clinic/requests/{id}/reject — 미승인."""

    permission_classes = [FeatureRequired(FeatureKey.CLINIC_ASSIGN)]

    def post(self, request, clinic_id):
        clinic_request = _load_clinic_request(clinic_id)
        if clinic_request is None:
            return Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)
        body = request.data if isinstance(request.data, dict) else {}
        try:
            clinic_admin.reject(clinic_request, body.get("reason"))
        except booking.ClinicError as error:
            return Response({"detail": error.message}, status=error.http_status)
        return Response(clinic_admin.queue_row(clinic_request))


class AdminClinicAttendanceView(APIView):
    """POST /api/admin/clinic/requests/{id}/attendance — 출결 처리·노쇼."""

    permission_classes = [FeatureRequired(FeatureKey.CLINIC_ASSIGN)]

    def post(self, request, clinic_id):
        clinic_request = _load_clinic_request(clinic_id)
        if clinic_request is None:
            return Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)
        body = request.data if isinstance(request.data, dict) else {}
        value = body.get("status")
        if value not in (
            ClinicRequest.AttendanceStatus.PRESENT,
            ClinicRequest.AttendanceStatus.ABSENT,
        ):
            return Response(
                {"detail": "status는 출석 또는 결석이어야 합니다."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            clinic_request, student = clinic_admin.mark_attendance(
                clinic_request, value, request.user
            )
        except booking.ClinicError as error:
            return Response({"detail": error.message}, status=error.http_status)
        payload = clinic_admin.queue_row(clinic_request)
        payload["student"]["noshow_count"] = student.noshow_count
        payload["student"]["clinic_banned"] = student.clinic_banned
        return Response(payload)


class AdminClinicUnbanView(APIView):
    """POST /api/admin/clinic/students/{student_id}/unban — 제한 해제.

    **대표 전용(IsOwner)**: 노쇼 영구제한 해제는 key_considerations §2 의
    대표 전용 민감 기능 **후보**라 범위 확정 전까지 일단 대표만 연다
    (닫힘이 안전 기본값). 확정 시 기능 키 축(OWNER_ONLY_FEATURES)으로 이관.
    """

    permission_classes = [IsOwner]

    def post(self, request, student_id):
        student = Student.objects.filter(pk=student_id).first()
        if student is None:
            return Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)
        try:
            clinic_admin.unban(student)
        except booking.ClinicError as error:
            return Response({"detail": error.message}, status=error.http_status)
        return Response(
            {
                "student_id": student.student_id,
                "clinic_banned": student.clinic_banned,
                "noshow_count": student.noshow_count,
            }
        )


class AdminClinicCriteriaView(APIView):
    """GET /api/admin/clinic/eval-criteria — 활성 평가 항목."""

    permission_classes = [FeatureRequired(FeatureKey.CLINIC_ASSIGN)]

    def get(self, request):
        return Response({"criteria": clinic_admin.criteria_rows()})


class AdminClinicEvaluationView(APIView):
    """POST /api/admin/clinic/requests/{id}/evaluation — 항목별 평가 기록."""

    permission_classes = [FeatureRequired(FeatureKey.CLINIC_ASSIGN)]

    def post(self, request, clinic_id):
        clinic_request = _load_clinic_request(clinic_id)
        if clinic_request is None:
            return Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)
        body = request.data if isinstance(request.data, dict) else {}
        error = self._validate(body)
        if error is not None:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        try:
            evaluation = clinic_admin.record_evaluation(
                clinic_request, body["items"], body.get("overall_result"), request.user
            )
        except booking.ClinicError as err:
            return Response({"detail": err.message}, status=err.http_status)
        return Response(clinic_admin.evaluation_payload(evaluation))

    @staticmethod
    def _validate(body):
        """전량 검증 후에만 저장(출결 PUT 선례) — 항목·판정 값집합·활성 항목."""
        items = body.get("items")
        if not isinstance(items, list) or not items:
            return "items(항목별 판정 리스트)가 필요합니다."
        active_ids = set(
            ClinicEvalCriteria.objects.filter(is_active=True).values_list(
                "criteria_id", flat=True
            )
        )
        for entry in items:
            if not isinstance(entry, dict) or not _is_int(entry.get("criteria_id")):
                return "criteria_id가 올바르지 않습니다."
            if entry["criteria_id"] not in active_ids:
                return "활성 평가 항목이 아닙니다."
            if entry.get("result") not in ClinicEvaluationItem.Result.values:
                return "result는 충족 또는 미충족이어야 합니다."
        overall = body.get("overall_result")
        if overall is not None and overall not in ("적격", "부적격"):
            return "overall_result는 적격 또는 부적격이어야 합니다."
        return None

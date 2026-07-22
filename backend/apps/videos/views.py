"""videos 뷰 — 동보 신청 API 4차 슬라이스 (PRD 3.2.3 예비 경로·§4).

- POST /api/student/makeup-request      학생 본인 결석의 동보 신청 (IsStudent)
- POST /api/parent/makeup-request       자녀 결석의 동보 신청 (IsParent)
- GET  /api/admin/makeup-requests       신청 목록 (영상지급관리)
- POST /api/admin/makeup-requests/{id}/approve  승인 = 지급완료 + VideoGrant(동보)
- POST /api/admin/makeup-requests/{id}/reject   거절 전환

**자격 강제(§4 상태 기반 노출)**: 동보 신청은 결석생에게만 존재한다 — 본인
(자녀)의 `결석` 출결이 아니면 이 API 자체가 4xx 다. 소유 밖 출결은 존재
여부와 무관하게 404(2차 슬라이스 자녀 소유 검증 패턴 — 존재 비노출),
소유 안이지만 결석이 아니면 400.

**중복 계약**: 같은 결석에 신청/승인/지급완료가 하나라도 있으면 400 —
거절된 신청만 재신청을 허용한다(관리자 재검토 경로).

지급 체인은 apps.videos.makeup.complete_makeup 공용 서비스가 담당한다
(관리자체크 경로와 단일 구현 — 3차 슬라이스 grant_makeup 과 공유).
"""
from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.features import FeatureKey
from apps.accounts.models import Parent, ParentStudent, Student
from apps.accounts.permissions import FeatureRequired, IsParent, IsStudent
from apps.grades.models import Attendance

from .makeup import complete_makeup
from .models import MakeupGrant

_NOT_FOUND_MESSAGE = "찾을 수 없습니다."
# 거절만 재신청 허용 — 신청/승인/지급완료는 살아있는 신청으로 본다(중복 400).
_ACTIVE_STATUSES = (
    MakeupGrant.Status.REQUESTED,
    MakeupGrant.Status.APPROVED,
    MakeupGrant.Status.GRANTED,
)


def _iso(value):
    """aware datetime → Asia/Seoul 로컬 ISO 문자열(2차 슬라이스 표기 선례)."""
    return timezone.localtime(value).isoformat() if value else None


def _makeup_block(makeup):
    """동보 요약 블록 — 신청·승인·거절 응답 공용(프런트 재조회 불필요 계약).

    호출측은 attendance__session__course_week__course 를 select_related 로
    로드해 둔다(쿼리 수 계약).
    """
    attendance = makeup.attendance
    week = attendance.session.course_week if attendance else None
    return {
        "makeup_id": makeup.makeup_id,
        "student_id": makeup.student_id,
        "attendance_id": makeup.attendance_id,
        "source": makeup.source,
        "status": makeup.status,
        "session_date": (
            attendance.session.session_date.isoformat() if attendance else None
        ),
        "week_no": week.week_no if week else None,
        "course_name": week.course.name if week else None,
        "granted_at": _iso(makeup.granted_at),
        "created_at": _iso(makeup.created_at),
    }


def _create_makeup_request(request, source, owner_filter):
    """소비자 신청 공통 처리 — owner_filter 가 학생/학부모 소유 경계를 결정한다."""
    body = request.data if isinstance(request.data, dict) else {}
    attendance_id = body.get("attendance_id")
    if not isinstance(attendance_id, int) or isinstance(attendance_id, bool):
        return Response(
            {"detail": "attendance_id가 필요합니다."}, status=status.HTTP_400_BAD_REQUEST
        )
    attendance = (
        Attendance.objects.select_related("session__course_week__course")
        .filter(pk=attendance_id, **owner_filter)
        .first()
    )
    if attendance is None:
        # 소유 밖 출결은 존재 여부와 무관하게 404 — 타인 결석을 노출하지 않는다
        return Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)
    if attendance.status != Attendance.Status.ABSENT:
        # §4: 결석이 없으면 동보 신청 자격 자체가 없다
        return Response(
            {"detail": "결석 출결에만 동보를 신청할 수 있습니다."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if MakeupGrant.objects.filter(
        attendance=attendance, status__in=_ACTIVE_STATUSES
    ).exists():
        return Response(
            {"detail": "이미 동보 신청 또는 지급이 있는 결석입니다."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    makeup = MakeupGrant.objects.create(
        student_id=attendance.student_id,
        attendance=attendance,
        source=source,
        requested_by=request.user,
    )
    return Response({"makeup": _makeup_block(makeup)}, status=status.HTTP_201_CREATED)


class StudentMakeupRequestView(APIView):
    """POST /api/student/makeup-request — 본인 결석의 동보 신청(예비 경로)."""

    permission_classes = [IsStudent]

    def post(self, request):
        student = Student.objects.filter(user=request.user).first()
        if student is None:
            # 학생 role 인데 students 행이 없는 예외 상태 — 닫힘으로 방어
            return Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)
        return _create_makeup_request(
            request, MakeupGrant.Source.STUDENT_REQUEST, {"student": student}
        )


class ParentMakeupRequestView(APIView):
    """POST /api/parent/makeup-request — 자녀 결석의 동보 신청(예비 경로)."""

    permission_classes = [IsParent]

    def post(self, request):
        parent = Parent.objects.filter(user=request.user).first()
        if parent is None:
            return Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)
        child_ids = ParentStudent.objects.filter(parent=parent).values_list(
            "student_id", flat=True
        )
        return _create_makeup_request(
            request, MakeupGrant.Source.PARENT_REQUEST, {"student_id__in": child_ids}
        )


class AdminMakeupRequestListView(APIView):
    """GET /api/admin/makeup-requests?status= — 동보 신청 목록(처리 대기열)."""

    permission_classes = [FeatureRequired(FeatureKey.VIDEO_GRANT_ADMIN)]

    def get(self, request):
        rows = MakeupGrant.objects.select_related(
            "student__user", "requested_by", "attendance__session__course_week__course"
        ).order_by("makeup_id")
        raw_status = request.query_params.get("status")
        if raw_status:
            if raw_status not in MakeupGrant.Status.values:
                return Response(
                    {"detail": "status 값이 올바르지 않습니다(신청/승인/지급완료/거절)."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            rows = rows.filter(status=raw_status)
        return Response({"requests": [self._row(m) for m in rows]})

    @staticmethod
    def _row(makeup):
        block = _makeup_block(makeup)
        student = makeup.student
        block["student"] = {
            "student_id": student.student_id,
            "name": student.user.name if student.user else None,
            "unique_id": student.unique_id,
        }
        block["requested_by"] = makeup.requested_by.name if makeup.requested_by else None
        return block


class AdminMakeupApproveView(APIView):
    """POST /api/admin/makeup-requests/{id}/approve — 지급완료 + VideoGrant 체인."""

    permission_classes = [FeatureRequired(FeatureKey.VIDEO_GRANT_ADMIN)]

    def post(self, request, makeup_id):
        makeup = (
            MakeupGrant.objects.select_related("attendance__session__course_week__course")
            .filter(pk=makeup_id)
            .first()
        )
        if makeup is None:
            return Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)
        if makeup.status != MakeupGrant.Status.REQUESTED:
            return Response(
                {"detail": "이미 처리된 신청입니다."}, status=status.HTTP_400_BAD_REQUEST
            )
        attendance = makeup.attendance
        if attendance is None:
            return Response(
                {"detail": "결석 근거 회차가 없는 신청입니다."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if attendance.status != Attendance.Status.ABSENT:
            # 출결 정정으로 결석이 아니게 된 신청 — 출석자동 지급과 이중 지급 차단
            return Response(
                {"detail": "결석 출결이 아니어서 지급할 수 없습니다(출결 정정됨)."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if attendance.session.course_week is None:
            return Response(
                {"detail": "커리큘럼 주차가 매핑되지 않은 회차입니다."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if (
            MakeupGrant.objects.filter(
                attendance=attendance, status=MakeupGrant.Status.GRANTED
            )
            .exclude(pk=makeup.pk)
            .exists()
        ):
            # 관리자체크(1차 경로)가 선행 지급한 결석 — 이중 지급 차단
            return Response(
                {"detail": "이미 동보가 지급된 결석입니다."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        now = timezone.now()
        with transaction.atomic():
            grant = complete_makeup(makeup, request.user, now)
        return Response(
            {
                "makeup": _makeup_block(makeup),
                "video_grant": {
                    "grant_id": grant.grant_id,
                    "student_id": grant.student_id,
                    "course_week_id": grant.course_week_id,
                    "source": grant.source,
                    "granted_at": _iso(grant.granted_at),
                    "expires_at": _iso(grant.expires_at),
                },
            }
        )


class AdminMakeupRejectView(APIView):
    """POST /api/admin/makeup-requests/{id}/reject — 거절 전환."""

    permission_classes = [FeatureRequired(FeatureKey.VIDEO_GRANT_ADMIN)]

    def post(self, request, makeup_id):
        makeup = (
            MakeupGrant.objects.select_related("attendance__session__course_week__course")
            .filter(pk=makeup_id)
            .first()
        )
        if makeup is None:
            return Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)
        if makeup.status != MakeupGrant.Status.REQUESTED:
            return Response(
                {"detail": "이미 처리된 신청입니다."}, status=status.HTTP_400_BAD_REQUEST
            )
        makeup.status = MakeupGrant.Status.REJECTED
        makeup.save(update_fields=["status"])
        return Response({"makeup": _makeup_block(makeup)})

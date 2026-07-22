"""grades 뷰 — 출결 입력 3차 + 성적·성적표 조회 5차 슬라이스.

3차(PRD 3.1.6·3.1.4①·3.2.3):
- GET  /api/admin/attendance/sessions            회차 목록 (출결입력)
- GET  /api/admin/attendance/sessions/{id}       회차 명단 + 출결 + 집계 (출결입력)
- PUT  /api/admin/attendance/sessions/{id}       출결 upsert + 파생 트리거 (출결입력)
- POST /api/admin/attendance/makeup              동보 관리자 체크 (영상지급관리)

5차(PRD 3.2.1·3.1.1·§4 — 전부 조회 전용):
- GET /api/student/grades                        내 시험 목록 + 회차별 추이 (IsStudent)
- GET /api/student/grades/{exam_id}              성적표 상세 (IsStudent)
- GET /api/parent/grades[?student_id=]           자녀 성적 목록 (IsParent, 읽기 전용)
- GET /api/parent/grades/{exam_id}[?student_id=] 자녀 성적표 상세 (IsParent)
- GET /api/admin/exams                           시험 목록 (성적처리)
- GET /api/admin/exams/{exam_id}                 시험 상세 (성적처리)

페이로드 조립은 report(소비자)·exam_admin(관리자) 서비스가 담당 — 뷰는
역할·기능 키 게이트, 입력 검증, 대상 학생 결정(학부모는 자녀 소유 검증 —
2차 슬라이스 home 선례)만 한다.

**동보 기능 키 판단**: 동보 체크는 곧 영상 권한 지급 행위다(PRD 3.2.3 "체크하면
즉시 복습영상 권한 자동 부여") — 출결입력이 아니라 `영상지급관리`(FeatureKey.
VIDEO_GRANT_ADMIN, "3.1.3·3.1.4 권한 지급/회수")가 맞는 축. 상담 기록 자체
(makeup_requested 체크)는 상담기록 키의 소관이고, 여기는 지급만 담당한다.
관리자 프리셋은 두 키를 모두 가지므로 운영 동선은 그대로다.

SSOT 쓰기·트리거·페이로드 조립은 attendance_admin 서비스가 담당 — 뷰는
기능 키 게이트·입력 검증·상태 코드 결정만 한다(2차 슬라이스 home 선례).
"""
import datetime

from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.features import FeatureKey
from apps.accounts.models import Parent, ParentStudent, Student
from apps.accounts.permissions import FeatureRequired, IsParent, IsStudent
from apps.videos.models import MakeupGrant

from . import attendance_admin, exam_admin, report
from .models import Attendance, ClassSession

_NOT_FOUND_MESSAGE = "찾을 수 없습니다."
_STATUS_VALUES = set(Attendance.Status.values)


class AttendanceSessionListView(APIView):
    """GET /api/admin/attendance/sessions?course_id=&date= — 회차 목록."""

    permission_classes = [FeatureRequired(FeatureKey.ATTENDANCE_ENTRY)]

    def get(self, request):
        sessions = ClassSession.objects.select_related("course_week__course").order_by(
            "session_date", "session_id"
        )
        raw_course_id = request.query_params.get("course_id")
        if raw_course_id:
            try:
                sessions = sessions.filter(course_week__course_id=int(raw_course_id))
            except ValueError:
                return Response(
                    {"detail": "course_id가 올바르지 않습니다."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        raw_date = request.query_params.get("date")
        if raw_date:
            try:
                sessions = sessions.filter(session_date=datetime.date.fromisoformat(raw_date))
            except ValueError:
                return Response(
                    {"detail": "date 형식은 YYYY-MM-DD 입니다."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        return Response(
            {"sessions": [attendance_admin.session_block(s) for s in sessions]}
        )


class AttendanceSessionDetailView(APIView):
    """GET·PUT /api/admin/attendance/sessions/{id} — 명단 조회·출결 upsert."""

    permission_classes = [FeatureRequired(FeatureKey.ATTENDANCE_ENTRY)]

    def get(self, request, session_id):
        session = attendance_admin.load_session(session_id)
        if session is None:
            return Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)
        roster = attendance_admin.load_roster(session)
        att_map = attendance_admin.load_attendance_map(
            session, [s.student_id for s in roster]
        )
        return Response(attendance_admin.build_detail_payload(session, roster, att_map))

    def put(self, request, session_id):
        session = attendance_admin.load_session(session_id)
        if session is None:
            return Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)
        if session.course_week is None:
            # 명단은 주차→강좌에서 산정된다 — 미매핑 회차는 입력 대상이 없다
            return Response(
                {"detail": "커리큘럼 주차가 매핑되지 않은 회차입니다."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        roster = attendance_admin.load_roster(session)
        roster_ids = [s.student_id for s in roster]
        error = _validate_entries(request.data, set(roster_ids))
        if error is not None:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        att_map, triggers = attendance_admin.apply_entries(
            session, request.data, request.user, roster_ids
        )
        payload = attendance_admin.build_detail_payload(session, roster, att_map)
        payload["triggers"] = triggers
        return Response(payload)


def _validate_entries(data, roster_ids):
    """PUT 본문 검증 — 오류 메시지 또는 None. 전량 검증 후에만 저장(원자성)."""
    if not isinstance(data, list):
        return "요청 본문은 학생별 출결 리스트여야 합니다."
    seen = set()
    for entry in data:
        if not isinstance(entry, dict):
            return "요청 본문은 학생별 출결 리스트여야 합니다."
        student_id = entry.get("student_id")
        if not isinstance(student_id, int) or isinstance(student_id, bool):
            return "student_id가 올바르지 않습니다."
        if student_id in seen:
            return "학생이 중복 포함되어 있습니다."
        seen.add(student_id)
        if student_id not in roster_ids:
            return "명단에 없는 학생이 포함되어 있습니다."
        if entry.get("status") not in _STATUS_VALUES:
            return "status 값이 올바르지 않습니다(출석/결석/지각)."
        if "exam_taken" in entry and not (
            entry["exam_taken"] is None or isinstance(entry["exam_taken"], bool)
        ):
            return "exam_taken 값이 올바르지 않습니다."
    return None


class MakeupCheckView(APIView):
    """POST /api/admin/attendance/makeup — 결석 근거 동보 지급(관리자 체크)."""

    permission_classes = [FeatureRequired(FeatureKey.VIDEO_GRANT_ADMIN)]

    def post(self, request):
        body = request.data if isinstance(request.data, dict) else {}
        student_id = body.get("student_id")
        attendance_id = body.get("attendance_id")
        for value in (student_id, attendance_id):
            if not isinstance(value, int) or isinstance(value, bool):
                return Response(
                    {"detail": "student_id·attendance_id가 필요합니다."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        attendance = (
            Attendance.objects.select_related("session__course_week")
            .filter(pk=attendance_id)
            .first()
        )
        if attendance is None:
            return Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)
        if attendance.student_id != student_id:
            return Response(
                {"detail": "student_id가 결석 출결과 일치하지 않습니다."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if attendance.status != Attendance.Status.ABSENT:
            # 동보는 결석 보강이다(PRD 3.2.3 정의) — 출석·지각 근거 지급 차단
            return Response(
                {"detail": "결석 출결에만 동보를 지급할 수 있습니다."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if attendance.session.course_week is None:
            return Response(
                {"detail": "커리큘럼 주차가 매핑되지 않은 회차입니다."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if MakeupGrant.objects.filter(
            attendance=attendance, status=MakeupGrant.Status.GRANTED
        ).exists():
            return Response(
                {"detail": "이미 동보가 지급된 결석입니다."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        makeup, grant = attendance_admin.grant_makeup(attendance, request.user)
        return Response(
            {
                "makeup": {
                    "makeup_id": makeup.makeup_id,
                    "student_id": makeup.student_id,
                    "attendance_id": makeup.attendance_id,
                    "source": makeup.source,
                    "status": makeup.status,
                    "granted_at": timezone_iso(makeup.granted_at),
                },
                "video_grant": {
                    "grant_id": grant.grant_id,
                    "student_id": grant.student_id,
                    "course_week_id": grant.course_week_id,
                    "source": grant.source,
                    "granted_at": timezone_iso(grant.granted_at),
                    "expires_at": timezone_iso(grant.expires_at),
                },
            },
            status=status.HTTP_201_CREATED,
        )


def timezone_iso(value):
    """aware datetime → Asia/Seoul 로컬 ISO 문자열(2차 슬라이스 표기 선례)."""
    return timezone.localtime(value).isoformat() if value else None


# --- 5차 슬라이스: 성적·성적표 조회 --------------------------------------


def _my_student(request):
    """로그인 학생의 students 행. 없으면 None(예외 상태 — 닫힘 방어, 2차 선례)."""
    return Student.objects.select_related("user").filter(user=request.user).first()


def _resolve_child(request):
    """학부모의 대상 자녀 결정 — (student, error_response) (2차 슬라이스 패턴).

    parent_students 에 연결된 자녀만 조회 가능. 소유 밖 student_id 는 존재
    여부와 무관하게 404 — 타인 자녀 존재를 노출하지 않는다(§4). student_id
    생략 시 첫 자녀(student_id 오름차순 — /api/me children 드롭다운 순서).
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
        .select_related("student__user")
        .order_by("student_id")
    )
    if student_id is None:
        student = links[0].student if links else None
    else:
        student = next((link.student for link in links if link.student_id == student_id), None)
    if student is None:
        return None, Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)
    return student, None


class StudentGradeListView(APIView):
    """GET /api/student/grades — 내 시험 목록(회차순) + 회차별 추이."""

    permission_classes = [IsStudent]

    def get(self, request):
        student = _my_student(request)
        if student is None:
            return Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)
        return Response(report.build_grades_list(student))


class StudentGradeReportView(APIView):
    """GET /api/student/grades/{exam_id} — 내 성적표 상세.

    내 성적이 없는 시험은 404 — 시험 존재를 노출하지 않는다(§4).
    """

    permission_classes = [IsStudent]

    def get(self, request, exam_id):
        student = _my_student(request)
        if student is None:
            return Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)
        payload = report.build_report(student, exam_id)
        if payload is None:
            return Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)
        return Response(payload)


class ParentGradeListView(APIView):
    """GET /api/parent/grades?student_id= — 자녀 성적 목록(읽기 전용, PRD 3.4)."""

    permission_classes = [IsParent]

    def get(self, request):
        student, error = _resolve_child(request)
        if error is not None:
            return error
        return Response(report.build_grades_list(student))


class ParentGradeReportView(APIView):
    """GET /api/parent/grades/{exam_id}?student_id= — 자녀 성적표 상세."""

    permission_classes = [IsParent]

    def get(self, request, exam_id):
        student, error = _resolve_child(request)
        if error is not None:
            return error
        payload = report.build_report(student, exam_id)
        if payload is None:
            return Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)
        return Response(payload)


class AdminExamListView(APIView):
    """GET /api/admin/exams — 시험 목록(응시자 수·평균·처리 상태)."""

    permission_classes = [FeatureRequired(FeatureKey.GRADE_PROCESSING)]

    def get(self, request):
        return Response(exam_admin.build_exam_list())


class AdminExamDetailView(APIView):
    """GET /api/admin/exams/{exam_id} — 학생별 점수 테이블 + 문항별 정답률."""

    permission_classes = [FeatureRequired(FeatureKey.GRADE_PROCESSING)]

    def get(self, request, exam_id):
        exam = exam_admin.load_exam(exam_id)
        if exam is None:
            return Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)
        return Response(exam_admin.build_exam_detail(exam))

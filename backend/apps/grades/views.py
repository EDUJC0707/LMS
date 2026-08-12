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
- GET  /api/admin/exams                          시험 목록 (성적처리)
- POST /api/admin/exams                          시험 만들기 (성적처리)
- GET  /api/admin/exams/{exam_id}                시험 상세 (성적처리)
- GET/PUT /api/admin/exams/{exam_id}/questions   정답 키 (성적처리)
- GET/POST /api/admin/exams/{exam_id}/sheets     보정 목록 · 스캔 업로드 (성적처리)
- POST /api/admin/exams/{exam_id}/reread         저장된 스캔 재판독 → 202 (성적처리)
- GET  /api/admin/omr-batches/{task_id}          판독 진행 상태 (성적처리)
- GET/PATCH /api/admin/sheets/{sheet_id}         보정 화면 한 장 (성적처리)
- GET  /api/admin/sheets/{sheet_id}/scan         스캔 원본 이미지 (성적처리)

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
import uuid

from celery.result import AsyncResult
from django.core.files.storage import default_storage
from django.http import FileResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.features import FeatureKey
from apps.accounts.models import Parent, ParentStudent, Student, User
from apps.accounts.permissions import FeatureRequired, IsParent, IsStudent
from apps.videos.models import MakeupGrant

from . import attendance_admin, exam_admin, omr_store, report, tasks, workbook, workbook_admin
from .models import AnswerSheet, Attendance, ClassSession, Exam, WorkbookSubmission
from .omr import card

_NOT_FOUND_MESSAGE = "찾을 수 없습니다."
_STATUS_VALUES = set(Attendance.Status.values)
# 동보 지급을 걸 수 있는 출결 — `결석`(보강 미정) 과 이미 동보로 찍힌 결석.
# 후자를 허용해야 관리자 체크가 멱등하게 400(이미 지급됨)으로 떨어진다.
_MAKEUP_ELIGIBLE_STATUSES = {
    Attendance.Status.ABSENT,
    Attendance.Status.ABSENT_MAKEUP,
}


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
        roster_ids = attendance_admin.entry_target_ids(roster)
        error = _validate_entries(
            request.data, set(roster_ids), attendance_admin.withdrawn_ids(roster)
        )
        if error is not None:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        att_map, triggers = attendance_admin.apply_entries(
            session, request.data, request.user, roster_ids
        )
        payload = attendance_admin.build_detail_payload(session, roster, att_map)
        payload["triggers"] = triggers
        return Response(payload)


def _validate_entries(data, roster_ids, withdrawn_ids):
    """PUT 본문 검증 — 오류 메시지 또는 None. 전량 검증 후에만 저장(원자성).

    퇴원생은 명단에 **보이지만** 입력 대상이 아니다(attendance_admin 계약) —
    "명단에 없는 학생"과 다른 사유이므로 문구를 갈라 준다.
    """
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
        if student_id in withdrawn_ids:
            return "퇴원 학생에게는 출결을 입력할 수 없습니다."
        if student_id not in roster_ids:
            return "명단에 없는 학생이 포함되어 있습니다."
        if entry.get("status") not in _STATUS_VALUES:
            return f"status 값이 올바르지 않습니다({'/'.join(Attendance.Status.values)})."
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
        if attendance.status not in _MAKEUP_ELIGIBLE_STATUSES:
            # 동보는 결석 보강이다(PRD 3.2.3 정의) — 출석 근거 지급 차단.
            # `결석(현보)` 도 막는다: 현장 보강을 이미 받은 결석이라 동영상
            # 보강을 겹쳐 줄 이유가 없다(권한 2행이 되고 사실도 어긋난다).
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
        makeup, grants = attendance_admin.grant_makeup(attendance, request.user)
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
                # 지급 단위가 영상이라 행이 여러 개다(2026-08-04). 응답은 만든
                # 행 전부를 싣는다 — 하나만 실으면 "몇 개 지급됐나"가 사라진다.
                "video_grants": [
                    {
                        "grant_id": g.grant_id,
                        "student_id": g.student_id,
                        "video_id": g.video_id,
                        "source": g.source,
                        "granted_at": timezone_iso(g.granted_at),
                        "expires_at": timezone_iso(g.expires_at),
                    }
                    for g in grants
                ],
            },
            status=status.HTTP_201_CREATED,
        )


class AttendanceWithdrawView(APIView):
    """POST /api/admin/attendance/withdraw — 출결 화면에서 퇴원 처리 (PRD 3.1.6).

    기능 키가 `출결입력` 인 근거: 퇴원을 누르는 사람은 명단을 보고 있는 담임이고
    (features.ATTENDANCE_ENTRY 주석이 이미 "출결 SSOT 입력·퇴원 처리"로 묶어 뒀다),
    출결 값집합에 `퇴원` 을 넣지 않는 대신 이 버튼이 그 자리를 대신한다.

    body: `{"student_id": int, "reason": str?}` — 이미 퇴원인 학생은 최초 처리
    이력을 지키기 위해 덮어쓰지 않는다(멱등, 200).
    """

    permission_classes = [FeatureRequired(FeatureKey.ATTENDANCE_ENTRY)]

    def post(self, request):
        body = request.data if isinstance(request.data, dict) else {}
        student_id = body.get("student_id")
        if not isinstance(student_id, int) or isinstance(student_id, bool):
            return Response(
                {"detail": "student_id가 올바르지 않습니다."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        student = Student.objects.filter(pk=student_id).first()
        if student is None:
            return Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)
        raw_reason = body.get("reason")
        reason = raw_reason.strip() if isinstance(raw_reason, str) else None
        attendance_admin.withdraw_student(
            student, request.user, timezone.now(), reason=reason
        )
        return Response(
            {
                "student_id": student.student_id,
                "enrollment_status": student.enrollment_status,
                "withdrawn_at": timezone_iso(student.withdrawn_at),
                "withdrawn_reason": student.withdrawn_reason,
            }
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


# --- 7차 슬라이스: 워크북 사진 업로드·열람 --------------------------------


def _to_int(value):
    """요청 파라미터 → int(실패 시 None). 멀티파트·쿼리 문자열 공용."""
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class AdminWorkbookUploadView(APIView):
    """POST /api/admin/workbook/upload — 워크북 마지막 페이지 사진 업로드.

    멀티파트 `images`(복수 허용) + `student_id`(잠정 매핑 — 설계 NN) +
    `session_id`(선택). 저장·검증 계약은 workbook_admin 모듈 docstring.
    """

    permission_classes = [FeatureRequired(FeatureKey.WORKBOOK_UPLOAD)]

    def post(self, request):
        files = request.FILES.getlist("images")
        error = workbook_admin.validate_files(files)
        if error is not None:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        student_id = _to_int(request.data.get("student_id"))
        if student_id is None:
            return Response(
                {"detail": "student_id가 올바르지 않습니다."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        student = Student.objects.filter(pk=student_id).first()
        if student is None:
            return Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)
        session = None
        raw_session_id = request.data.get("session_id")
        if raw_session_id not in (None, ""):
            session_id = _to_int(raw_session_id)
            if session_id is None:
                return Response(
                    {"detail": "session_id가 올바르지 않습니다."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            session = ClassSession.objects.filter(pk=session_id).first()
            if session is None:
                return Response(
                    {"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND
                )
        submissions = workbook_admin.create_submissions(files, student, session, request.user)
        return Response(
            {"submissions": [workbook_admin.admin_row(s) for s in submissions]},
            status=status.HTTP_201_CREATED,
        )


class AdminWorkbookListView(APIView):
    """GET /api/admin/workbook?session_id=&status= — 목록·미매핑 카운트(보정 화면)."""

    permission_classes = [FeatureRequired(FeatureKey.WORKBOOK_UPLOAD)]

    def get(self, request):
        session_id = None
        raw_session_id = request.query_params.get("session_id")
        if raw_session_id:
            session_id = _to_int(raw_session_id)
            if session_id is None:
                return Response(
                    {"detail": "session_id가 올바르지 않습니다."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        status_param = request.query_params.get("status") or None
        valid_statuses = set(WorkbookSubmission.MatchStatus.values) | {
            workbook_admin.PENDING_STATUS
        }
        if status_param is not None and status_param not in valid_statuses:
            return Response(
                {
                    "detail": (
                        "status 값이 올바르지 않습니다"
                        "(대기/자동매칭/수동확정/불일치/인식실패)."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(workbook_admin.build_admin_list(session_id, status_param))


class AdminWorkbookMatchView(APIView):
    """PATCH /api/admin/workbook/{submission_id}/match — 인식 결과 수용·수동확정.

    두 모드 중 정확히 하나만(8-9 결정 — 매칭 계약은 workbook_admin docstring):
    - `student_id`: 관리자 수동 지정 → 수동확정
    - `recognized_matching_key`(+`recognized_name`): 원번+이름 대조 자동 매칭
      시도 → 성공 자동매칭 / 실패 불일치. OCR 엔진(후속 슬라이스)과 관리자
      수동 입력이 같은 수용 계약을 쓴다.
    """

    permission_classes = [FeatureRequired(FeatureKey.WORKBOOK_UPLOAD)]

    def patch(self, request, submission_id):
        submission = (
            WorkbookSubmission.objects.select_related("student__user", "session", "uploaded_by")
            .filter(pk=submission_id)
            .first()
        )
        if submission is None:
            return Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)
        body = request.data if isinstance(request.data, dict) else {}
        raw_student_id = body.get("student_id")
        raw_matching_key = body.get("recognized_matching_key")
        matching_key = raw_matching_key.strip() if isinstance(raw_matching_key, str) else ""
        if (raw_student_id is not None) == bool(matching_key):
            return Response(
                {"detail": "student_id 또는 recognized_matching_key 중 하나만 보내야 합니다."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if raw_student_id is not None:
            student_id = _to_int(raw_student_id)
            if student_id is None:
                return Response(
                    {"detail": "student_id가 올바르지 않습니다."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            student = Student.objects.select_related("user").filter(pk=student_id).first()
            if student is None:
                return Response(
                    {"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND
                )
            workbook_admin.apply_manual_match(submission, student)
        else:
            raw_name = body.get("recognized_name")
            name = raw_name.strip() if isinstance(raw_name, str) else ""
            workbook_admin.apply_recognition(submission, matching_key, name or None)
        return Response({"submission": workbook_admin.admin_row(submission)})


class AdminWorkbookDetailView(APIView):
    """DELETE /api/admin/workbook/{submission_id} — 잘못 올린 사진 삭제.

    객체 권한: **업로더 본인 또는 상위 직원(관리자·대표)**만. 조교가 남의
    업로드를 지우는 것은 차단 — 파괴적 작업 최소 권한(key_considerations §5).
    파일도 함께 제거된다(workbook_admin.delete_submission).
    """

    permission_classes = [FeatureRequired(FeatureKey.WORKBOOK_UPLOAD)]

    def delete(self, request, submission_id):
        submission = WorkbookSubmission.objects.filter(pk=submission_id).first()
        if submission is None:
            return Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)
        is_uploader = submission.uploaded_by_id == request.user.pk
        if not is_uploader and request.user.role not in (User.Role.OWNER, User.Role.ADMIN):
            return Response(
                {"detail": "접근 권한이 없습니다."}, status=status.HTTP_403_FORBIDDEN
            )
        workbook_admin.delete_submission(submission)
        return Response(status=status.HTTP_204_NO_CONTENT)


class StudentWorkbookView(APIView):
    """GET /api/student/workbook — 내 확정 워크북 사진(노출 규칙은 workbook 모듈)."""

    permission_classes = [IsStudent]

    def get(self, request):
        student = _my_student(request)
        if student is None:
            return Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)
        return Response(workbook.build_workbook_payload(student))


class ParentWorkbookView(APIView):
    """GET /api/parent/workbook?student_id= — 자녀 워크북(소유 검증 — 2차 선례).

    학생과 같은 조립 함수 — PRD 3.1.1 리포트 '워크북 사진 링크'의 데이터 원천.
    """

    permission_classes = [IsParent]

    def get(self, request):
        student, error = _resolve_child(request)
        if error is not None:
            return error
        return Response(workbook.build_workbook_payload(student))


class AdminExamListView(APIView):
    """GET·POST /api/admin/exams — 시험 목록 / 시험 만들기."""

    permission_classes = [FeatureRequired(FeatureKey.GRADE_PROCESSING)]

    def get(self, request):
        return Response(exam_admin.build_exam_list())

    def post(self, request):
        name = str(request.data.get("name") or "").strip()
        raw_date = request.data.get("exam_date")
        if not name:
            return Response({"detail": "시험명을 입력하세요."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            exam_date = datetime.date.fromisoformat(str(raw_date))
        except (TypeError, ValueError):
            return Response(
                {"detail": "시험일 형식은 YYYY-MM-DD 입니다."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        kind = request.data.get("kind") or Exam.Kind.MINI
        if kind not in Exam.Kind.values:
            return Response(
                {"detail": f"시험 종류는 {'·'.join(Exam.Kind.values)} 중 하나입니다."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        exam = exam_admin.create_exam(
            name,
            exam_date,
            round_no=request.data.get("round_no") or None,
            target_grade=request.data.get("target_grade") or None,
            kind=kind,
            full_score=request.data.get("full_score") or None,
        )
        return Response({"exam_id": exam.pk}, status=status.HTTP_201_CREATED)


class AdminExamQuestionsView(APIView):
    """GET·PUT /api/admin/exams/{exam_id}/questions — 정답 키 조회·저장."""

    permission_classes = [FeatureRequired(FeatureKey.GRADE_PROCESSING)]

    def get(self, request, exam_id):
        exam = exam_admin.load_exam(exam_id)
        if exam is None:
            return Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)
        return Response(
            {"questions": exam_admin.question_rows(exam), "units": exam_admin.unit_options()}
        )

    def put(self, request, exam_id):
        exam = exam_admin.load_exam(exam_id)
        if exam is None:
            return Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)
        rows = request.data.get("questions")
        error = _validate_questions(rows)
        if error is not None:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            {"questions": exam_admin.save_questions(exam, rows), "units": exam_admin.unit_options()}
        )


class AdminExamSheetsView(APIView):
    """스캔 묶음 — GET 은 보정 화면 목록, POST 는 PDF 업로드."""

    permission_classes = [FeatureRequired(FeatureKey.GRADE_PROCESSING)]

    def get(self, request, exam_id):
        exam = exam_admin.load_exam(exam_id)
        if exam is None:
            return Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)
        # 종류를 함께 준다 — 보정 화면이 문항을 고칠지 점수를 고칠지가 여기서 갈리고,
        # 장 하나만 봐서는 알 수 없다(보류된 조사 카드는 점수도 비어 있다).
        return Response({"kind": exam.kind, "sheets": exam_admin.sheet_rows(exam)})

    def post(self, request, exam_id):
        exam = exam_admin.load_exam(exam_id)
        if exam is None:
            return Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)
        pdf = request.FILES.get("pdf")
        if pdf is None or not pdf.name.lower().endswith(".pdf"):
            return Response(
                {"detail": "스캔 PDF 파일을 올려 주세요."}, status=status.HTTP_400_BAD_REQUEST
            )
        try:
            question_count = int(request.data.get("question_count"))
        except (TypeError, ValueError):
            question_count = 0
        # 모의고사는 지면에 문항이 없다(성적 조사 카드) — 문항 수를 묻지 않는다.
        # 미니테스트는 카드가 20줄이고, 범위 밖을 그냥 넘기면 워커에서 ValueError
        # 로 죽어 사용자는 "판독 실패" 만 보게 된다 — 여기서 막는다.
        if exam.kind != Exam.Kind.MOCK and not 1 <= question_count <= card.ANSWER_QUESTIONS:
            return Response(
                {"detail": f"문항 수를 1~{card.ANSWER_QUESTIONS} 사이로 지정해 주세요."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        path = default_storage.save(
            f"omr-upload/{exam.pk}/{uuid.uuid4().hex}.pdf", pdf
        )
        task = tasks.ingest_omr_batch.delay(exam.pk, path, question_count)
        return Response({"task_id": task.id}, status=status.HTTP_202_ACCEPTED)


class AdminExamRereadView(APIView):
    """POST /api/admin/exams/{exam_id}/reread — 저장된 스캔으로 다시 판독.

    정답 키를 나중에 넣었거나 엔진이 좋아졌을 때 쓴다. 업로드와 같은 태스크·같은
    진행 조회를 쓴다 — 조교가 보기엔 "다시 채점" 버튼 하나다.
    """

    permission_classes = [FeatureRequired(FeatureKey.GRADE_PROCESSING)]

    def post(self, request, exam_id):
        exam = exam_admin.load_exam(exam_id)
        if exam is None:
            return Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)
        question_count = exam.questions.count()
        if exam.kind != Exam.Kind.MOCK and not question_count:
            return Response(
                {"detail": "정답 키를 먼저 입력해 주세요."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        task = tasks.reread_omr_sheets.delay(exam.pk, question_count)
        return Response({"task_id": task.id}, status=status.HTTP_202_ACCEPTED)


class AdminOmrBatchView(APIView):
    """GET /api/admin/omr-batches/{task_id} — 판독 진행 상태.

    상태는 Celery 결과 백엔드(Redis)가 들고 있다 — 진행률 테이블을 따로 두면
    태스크 결과와 두 벌이 되어 어긋난다.
    """

    permission_classes = [FeatureRequired(FeatureKey.GRADE_PROCESSING)]

    def get(self, request, task_id):
        result = AsyncResult(task_id)
        body = {"state": result.state}
        if result.successful():
            body["summary"] = result.result
        elif result.failed():
            body["detail"] = "판독에 실패했습니다. 파일을 확인하고 다시 올려 주세요."
        return Response(body)


class AdminSheetView(APIView):
    """GET/PATCH /api/admin/sheets/{sheet_id} — 보정 화면 한 장.

    PATCH 본문은 손댄 것만 보낸다: `student_id`(장의 주인 확정 — null 이면
    해제), `answers`({문항번호: "3"} — 무응답은 ""), `score`(모의고사 자기보고
    점수), `confirm`(값은 그대로 두고 기계 판독을 승인). 전부 없으면 400 —
    빈 PATCH 로 보정 잠금이 걸리면 조교가 안 본 장이 확인된 장으로 둔갑한다.
    """

    permission_classes = [FeatureRequired(FeatureKey.GRADE_PROCESSING)]

    def get(self, request, sheet_id):
        sheet = self._load(sheet_id)
        if sheet is None:
            return Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)
        return Response(exam_admin.sheet_detail(sheet))

    def patch(self, request, sheet_id):
        sheet = self._load(sheet_id)
        if sheet is None:
            return Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)
        data = request.data
        confirm = bool(data.get("confirm"))
        answers, error = _validate_marks(data.get("answers"))
        if error is None and "student_id" in data:
            student, error = _load_student(data["student_id"])
        else:
            student = omr_store.UNSET
        score = omr_store.UNSET
        if error is None and "score" in data:
            score, error = _validate_score(data["score"])
        if (
            error is None
            and student is omr_store.UNSET
            and score is omr_store.UNSET
            and not answers
            and not confirm
        ):
            error = "고칠 내용을 지정해 주세요."
        if error is not None:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        try:
            omr_store.correct_sheet(
                sheet, student=student, answers=answers, score=score, confirm=confirm
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(exam_admin.sheet_detail(self._load(sheet_id)))

    def _load(self, sheet_id):
        return (
            AnswerSheet.objects.filter(pk=sheet_id)
            .select_related("student__user", "exam")
            .first()
        )


class AdminSheetScanView(APIView):
    """GET /api/admin/sheets/{sheet_id}/scan — 스캔 원본 이미지.

    스토리지 URL 을 그대로 내주지 않는다. 지면에는 **실명과 전화번호 뒷자리**가
    찍혀 있어(개인정보) 링크 하나가 곧 유출 경로다 — 성적처리 키를 통과한
    요청에만 바이트를 흘린다.
    """

    permission_classes = [FeatureRequired(FeatureKey.GRADE_PROCESSING)]

    def get(self, request, sheet_id):
        sheet = AnswerSheet.objects.filter(pk=sheet_id).first()
        if sheet is None or not default_storage.exists(sheet.scan_image_path):
            return Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)
        return FileResponse(default_storage.open(sheet.scan_image_path, "rb"))


def _load_student(raw):
    """PATCH 의 student_id → (Student|None, 에러). null 은 '주인 해제'다."""
    if raw in (None, ""):
        return None, None
    student = Student.objects.filter(pk=raw).first()
    if student is None:
        return None, "그 학생을 찾을 수 없습니다."
    return student, None


def _validate_score(raw):
    """PATCH 의 score → (점수|None, 에러). null 은 '점수 지움'이다.

    조사 카드가 표현할 수 있는 범위는 0~59 다(10의 자리 1~5 + 1의 자리 0~9).
    그 밖의 수는 지면에서 온 값일 수 없으므로 조교의 오타다.
    """
    if raw in (None, ""):
        return None, None
    try:
        score = int(raw)
    except (TypeError, ValueError):
        return None, "점수는 숫자로 입력하세요."
    if not 0 <= score <= 59:
        return None, "점수는 0~59 사이입니다."
    return score, None


def _validate_marks(raw):
    """PATCH 의 answers → ({문항번호: 마킹}, 에러). 카드 밖 값은 여기서 막는다."""
    if not raw:
        return {}, None
    if not isinstance(raw, dict):
        return {}, "answers 는 {문항번호: 마킹} 이어야 합니다."
    marks = {}
    for key, value in raw.items():
        try:
            q_number = int(key)
        except (TypeError, ValueError):
            return {}, "문항번호가 올바르지 않습니다."
        text = str(value or "").strip()
        choices = [part.strip() for part in text.split(",") if part.strip()]
        if any(not part.isdigit() or not 1 <= int(part) <= card.ANSWER_CHOICES for part in choices):
            return {}, f"{q_number}번 마킹은 1~{card.ANSWER_CHOICES} 중에서 고릅니다."
        marks[q_number] = ",".join(choices)
    return marks, None


def _validate_questions(rows):
    """전량 검증 후에만 저장 — 반쯤 들어간 키는 반쯤 틀린 채점을 만든다."""
    if not isinstance(rows, list) or not rows:
        return "문항을 하나 이상 보내야 합니다."
    numbers = set()
    for row in rows:
        if not isinstance(row, dict):
            return "문항 형식이 올바르지 않습니다."
        try:
            number = int(row.get("q_number"))
        except (TypeError, ValueError):
            return "문항 번호가 올바르지 않습니다."
        if number in numbers:
            return f"문항 번호 {number} 가 중복입니다."
        numbers.add(number)
        if not str(row.get("answer") or "").strip():
            return f"{number}번 정답이 비어 있습니다."
        points = row.get("points")
        if points is not None and float(points) <= 0:
            return f"{number}번 배점이 0 이하입니다."
    return None


class AdminExamDetailView(APIView):
    """GET /api/admin/exams/{exam_id} — 학생별 점수 테이블 + 문항별 정답률."""

    permission_classes = [FeatureRequired(FeatureKey.GRADE_PROCESSING)]

    def get(self, request, exam_id):
        exam = exam_admin.load_exam(exam_id)
        if exam is None:
            return Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)
        return Response(exam_admin.build_exam_detail(exam))

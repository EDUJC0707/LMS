"""videos 뷰 — 복습영상 재생 + 동보 신청 API (PRD 3.1.3/3.1.4·3.2.3·§4).

- GET  /api/student/videos/{video_id}/playback  재생 (IsStudent)
- POST /api/student/videos/{video_id}/tamper    워터마크 제거 기록 (IsStudent)
- GET/POST   /api/admin/videos                  영상 목록·등록 (영상지급관리)
- PATCH      /api/admin/videos/{id}             메타·자산 수정
- POST       /api/admin/videos/{id}/publish     `공개` 전환(조건 강제)
- POST       /api/admin/videos/{id}/archive     `아카이브` 전환
- POST       /api/admin/videos/grants/{id}/revoke   개별 회수
- POST       /api/admin/videos/grants/{id}/unrevoke 회수 취소
- GET        /api/admin/videos/course-weeks     등록 폼 주차 선택지
- GET        /api/admin/videos/{id}/preview     관리자 미리보기(상태·권한 무시)
- POST       /api/admin/videos/uploads          업로드 자리 발급(파일은 서버를 안 지남)
- POST       /api/admin/videos/{id}/sync        업로드·인코딩 완료 확인
- POST /api/student/makeup-request      학생 본인 결석의 동보 신청 (IsStudent)
- POST /api/parent/makeup-request       자녀 결석의 동보 신청 (IsParent)
- GET  /api/admin/makeup-requests       신청 목록 (영상지급관리)
- POST /api/admin/makeup-requests/{id}/reject   거절 전환

**승인이 없다**(FLOW 3-4, 2026-08-18). 결석했다는 근거가 이미 출결 SSOT 에 있어
사람이 한 번 더 볼 것이 없다. 지급 조건은 **신청 + 결석 확인** 둘뿐이고 순서는
상관없다 — 결석이 이미 찍혀 있으면 받는 자리에서 바로 지급되고
(grades.attendance_admin.grant_makeup), 아직이면 출결표 저장이 낸다(트리거 ③).
구 `POST /admin/makeup-requests/{id}/approve` 와 `승인` 값은 제거됐다.
**클리닉은 그대로 승인제**다(FLOW 3-7) — 자리를 배정하는 일이라 별개다.

**신청이 출결 값을 바꾸지 않는다**(FLOW 3-4). `미입력` 인 칸에도 신청은 받지만
(결석이 확정되기 전에도 눌러 둘 수 있다) 출결표는 건드리지 않는다 — 학생이
눌렀다고 셀이 `결석(동보)` 가 되면 조교가 그 학생을 "아직 안 본 칸"에서 못 찾고,
`결석` 이 안 찍혀 영상이 영영 안 나간다.

**자격 강제(§4 상태 기반 노출)**: 소유 밖 출결은 존재 여부와 무관하게
404(2차 슬라이스 자녀 소유 검증 패턴 — 존재 비노출). 소유 안이라도
`출석`·`결석(현보)` 는 400 — 결석이 아닌 것이 확실한 값이다.

**중복 계약**: 같은 결석에 신청/지급완료가 하나라도 있으면 400 —
거절된 신청만 재신청을 허용한다(관리자 재검토 경로).

지급 체인은 apps.videos.makeup.complete_makeup 공용 서비스가 담당한다
(관리자체크·담임 입력 경로와 단일 구현).

재생의 권한 판정·워터마크 조립은 apps.videos.playback 이 담당하고 여기서는
None → 404 매핑만 한다(권한 원천·404 판단 근거는 그 모듈 docstring).
"""
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.features import FeatureKey
from apps.accounts.models import Parent, ParentStudent, Student
from apps.accounts.permissions import FeatureRequired, IsParent, IsStudent
from apps.grades import attendance_admin
from apps.grades.models import Attendance

from . import playback, video_admin
from .models import MakeupGrant, Video, VideoGrant, WatermarkTamper

_NOT_FOUND_MESSAGE = "찾을 수 없습니다."
# 거절만 재신청 허용 — 신청/지급완료는 살아있는 신청으로 본다(중복 400).
_ACTIVE_STATUSES = (MakeupGrant.Status.REQUESTED, MakeupGrant.Status.GRANTED)
# 결석이 아닌 것이 확실한 값 — 여기만 신청을 막는다. `미입력` 은 "아직 안 봤다"
# 이지 "왔다" 가 아니므로(FLOW 3-4) 막지 않는다.
_PRESENT_STATUSES = (Attendance.Status.PRESENT, Attendance.Status.ABSENT_ONSITE)


def _iso(value):
    """aware datetime → Asia/Seoul 로컬 ISO 문자열(2차 슬라이스 표기 선례)."""
    return timezone.localtime(value).isoformat() if value else None


def _optional_int(raw, label="값"):
    """빈 값은 None, 숫자가 아니면 ValueError(뷰가 400 으로 옮긴다)."""
    if raw in (None, ""):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ValueError(f"{label}이 올바르지 않습니다.") from None


def _makeup_block(makeup):
    """동보 요약 블록 — 신청·거절 응답 공용(프런트 재조회 불필요 계약).

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
    if attendance.status in _PRESENT_STATUSES:
        return Response(
            {"detail": "그 수업은 결석이 아닙니다."}, status=status.HTTP_400_BAD_REQUEST
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
    # **신청이 출결 값을 바꾸지 않는다**(FLOW 3-4). 결석이 이미 찍혀 있으면 조건
    # 둘이 다 찼으므로 여기서 나가고(지급 처리자는 비운다 — 받아 준 사람이 없다),
    # 아직이면 접수만 하고 출결표는 그대로 둔다. 미입력 칸을 신청이 `결석(동보)`
    # 로 덮으면 조교가 그 학생을 "아직 안 본 칸"에서 못 찾고, `결석` 이 안 찍혀
    # 영상이 영영 안 나간다 — 지급은 결석이 찍히는 그 자리(트리거 ③)가 낸다.
    if attendance.status in Attendance.ABSENT_STATUSES - {Attendance.Status.ABSENT_ONSITE}:
        attendance_admin.grant_makeup(attendance, None)
    # fields 를 주면 그 필드만 다시 읽는다 — select_related 로 잡아 둔 회차·주차가
    # 살아 있어야 아래 블록이 추가 쿼리를 내지 않는다.
    makeup.refresh_from_db(fields=["status", "granted_at"])
    return Response({"makeup": _makeup_block(makeup)}, status=status.HTTP_201_CREATED)


class StudentVideoListView(APIView):
    """GET /api/student/videos — 지금 볼 수 있는 복습영상 목록.

    재생 API 가 받는 video_id 를 학생에게 알려 주는 유일한 자리다.
    판정은 재생과 같은 두 게이트를 쓴다(playback.build_video_list).
    """

    permission_classes = [IsStudent]

    def get(self, request):
        student = Student.objects.select_related("user").filter(user=request.user).first()
        if student is None:
            return Response({"videos": []})
        return Response({"videos": playback.build_video_list(student, timezone.now())})


class StudentVideoPlaybackView(APIView):
    """GET /api/student/videos/{video_id}/playback — 재생 정보 + 워터마크.

    자격 판정은 playback.build_playback 이 끝내고 여기서는 None → 404 만 한다
    (권한 없음·만료·회수·비공개·없는 번호가 전부 같은 404 — 존재 비노출).
    """

    permission_classes = [IsStudent]

    def get(self, request, video_id):
        student = Student.objects.select_related("user").filter(user=request.user).first()
        if student is None:
            # 학생 role 인데 students 행이 없는 예외 상태 — 닫힘으로 방어
            return Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)
        # 권한 활성 판정과 워터마크의 시청 날짜가 같은 한 시각을 쓰도록 여기서 1회 고정
        payload = playback.build_playback(student, video_id, timezone.now())
        if payload is None:
            return Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)
        return Response(payload)


class StudentWatermarkTamperView(APIView):
    """POST /api/student/videos/{video_id}/tamper — 워터마크가 제거됐다.

    화면이 스스로 신고한다. **막지 못하는 것을 기록으로 바꾸는 자리**이므로
    (WatermarkTamper 모델 docstring) 여기서 재생을 끊거나 화면에 무엇을 띄우지
    않는다 — 알리면 신고 요청부터 막는 법을 배우게 된다.

    권한을 보지 않는다. 지금 이 학생이 그 영상을 볼 자격이 있었는지보다
    **시도했다는 사실**이 기록의 대상이다. 없는 영상 번호는 조용히 무시한다 —
    잘못된 번호로 404 를 흘리면 존재 여부가 새어 나간다(§4).
    """

    permission_classes = [IsStudent]

    def post(self, request, video_id):
        student = Student.objects.filter(user=request.user).first()
        video = Video.objects.filter(pk=video_id).first()
        if student is not None and video is not None:
            WatermarkTamper.objects.create(student=student, video=video)
        # 성공·실패를 구분해 알리지 않는다(위 docstring).
        return Response(status=status.HTTP_204_NO_CONTENT)


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
                    {"detail": "status 값이 올바르지 않습니다(신청/지급완료/거절)."},
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
            "login_id": student.user.login_id if student.user else None,
            "matching_key": student.matching_key,
        }
        block["requested_by"] = makeup.requested_by.name if makeup.requested_by else None
        return block


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


# ── 복습영상 등록·관리 ────────────────────────────────────────────────
# 판정·조립은 video_admin 이 끝내고 여기서는 게이트·입력 형태·상태코드 매핑만
# 한다(모듈 docstring 에 관리 경로 계약이 있다).


class AdminVideoGrantListView(APIView):
    """GET /api/admin/videos/grants?video_id=&student_id= — 지급 내역(FLOW §5)."""

    permission_classes = [FeatureRequired(FeatureKey.VIDEO_GRANT_ADMIN)]

    def get(self, request):
        try:
            video_id = _optional_int(request.query_params.get("video_id"), "video_id")
            student_id = _optional_int(request.query_params.get("student_id"), "student_id")
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"grants": video_admin.list_grants(video_id, student_id)})


class AdminVideoGrantRevokeView(APIView):
    """POST /api/admin/videos/grants/{grant_id}/revoke — 개별 회수(FLOW §5).

    **수동 지급의 짝이 아니다.** 지급은 `출결 확정` 이 묶음으로 하고 손으로 하는
    것은 회수뿐이다 — 여기에 대응하는 지급 API 는 만들지 않는다.
    """

    permission_classes = [FeatureRequired(FeatureKey.VIDEO_GRANT_ADMIN)]

    def post(self, request, grant_id):
        grant = (
            VideoGrant.objects.select_related("student__user", "video")
            .filter(pk=grant_id)
            .first()
        )
        if grant is None:
            return Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)
        return Response({"grant": video_admin.grant_row(video_admin.revoke_grant(grant))})


class AdminVideoGrantUnrevokeView(APIView):
    """POST /api/admin/videos/grants/{grant_id}/unrevoke — 회수 취소(FLOW §5).

    회수의 짝이다. 만료는 **처음 준 시점 그대로** 둔다(video_admin.unrevoke_grant)
    — 다시 잡으면 이 버튼이 수동 지급의 뒷문이 된다.
    """

    permission_classes = [FeatureRequired(FeatureKey.VIDEO_GRANT_ADMIN)]

    def post(self, request, grant_id):
        grant = (
            VideoGrant.objects.select_related("student__user", "video")
            .filter(pk=grant_id)
            .first()
        )
        if grant is None:
            return Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)
        return Response({"grant": video_admin.grant_row(video_admin.unrevoke_grant(grant))})


class AdminVideoListView(APIView):
    """GET/POST /api/admin/videos — 관리 목록과 등록."""

    permission_classes = [FeatureRequired(FeatureKey.VIDEO_GRANT_ADMIN)]

    def get(self, request):
        status_filter = request.query_params.get("status") or None
        if status_filter and status_filter not in Video.Status.values:
            return Response(
                {"detail": "status 값이 올바르지 않습니다(준비중/공개/아카이브)."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        week_raw = request.query_params.get("course_week_id") or None
        week_id = None
        if week_raw is not None:
            try:
                week_id = int(week_raw)
            except (TypeError, ValueError):
                return Response(
                    {"detail": "course_week_id가 올바르지 않습니다."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        # 웹훅 대신 — 목록을 열 때 처리 중인 것만 Mux 에 물어본다
        # (video_admin.sync_pending 주석). 없으면 쿼리 0건이라 공짜다.
        video_admin.sync_pending()
        rows = [
            video_admin.video_row(video)
            for video in video_admin.list_videos(status_filter, week_id)
        ]
        return Response({"videos": rows})

    def post(self, request):
        fields, error = video_admin.parse_input(request.data)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        video, error = video_admin.create_video(fields)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            {"video": video_admin.video_row(video)}, status=status.HTTP_201_CREATED
        )


class AdminVideoDetailView(APIView):
    """PATCH /api/admin/videos/{video_id} — 부분 수정."""

    permission_classes = [FeatureRequired(FeatureKey.VIDEO_GRANT_ADMIN)]

    def patch(self, request, video_id):
        video = video_admin.load_video(video_id)
        if video is None:
            return Response(
                {"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND
            )
        fields, error = video_admin.parse_input(request.data, partial=True)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        video, error = video_admin.update_video(video, fields)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"video": video_admin.video_row(video)})


class AdminVideoPublishView(APIView):
    """POST /api/admin/videos/{video_id}/publish — `공개` 전환."""

    permission_classes = [FeatureRequired(FeatureKey.VIDEO_GRANT_ADMIN)]

    def post(self, request, video_id):
        video = video_admin.load_video(video_id)
        if video is None:
            return Response(
                {"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND
            )
        video, error = video_admin.publish(video)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"video": video_admin.video_row(video)})


class AdminVideoArchiveView(APIView):
    """POST /api/admin/videos/{video_id}/archive — `아카이브` 전환."""

    permission_classes = [FeatureRequired(FeatureKey.VIDEO_GRANT_ADMIN)]

    def post(self, request, video_id):
        video = video_admin.load_video(video_id)
        if video is None:
            return Response(
                {"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND
            )
        video, error = video_admin.archive(video)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"video": video_admin.video_row(video)})


class AdminVideoUploadView(APIView):
    """POST /api/admin/videos/uploads — 업로드 자리 발급.

    파일은 **브라우저에서 Mux 로 직접** 간다(mux.create_direct_upload 주석).
    여기서는 자리만 만들고 행을 먼저 만들어 유실을 막는다.
    """

    permission_classes = [FeatureRequired(FeatureKey.VIDEO_GRANT_ADMIN)]

    def post(self, request):
        fields, error = video_admin.parse_input(request.data)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        # 브라우저가 PUT 할 출처 — 아무 데서나 우리 자리로 올리지 못하게 한다.
        origin = request.headers.get("Origin") or request.build_absolute_uri("/").rstrip("/")
        result, error = video_admin.start_upload(fields, origin)
        if error:
            return Response({"detail": error}, status=status.HTTP_502_BAD_GATEWAY)
        video, upload_url = result
        return Response(
            {"video": video_admin.video_row(video), "upload_url": upload_url},
            status=status.HTTP_201_CREATED,
        )


class AdminVideoSyncView(APIView):
    """POST /api/admin/videos/{video_id}/sync — 처리 끝났는지 확인하고 반영."""

    permission_classes = [FeatureRequired(FeatureKey.VIDEO_GRANT_ADMIN)]

    def post(self, request, video_id):
        video = video_admin.load_video(video_id)
        if video is None:
            return Response(
                {"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND
            )
        video, error = video_admin.sync_upload(video)
        if error:
            return Response({"detail": error}, status=status.HTTP_502_BAD_GATEWAY)
        return Response({"video": video_admin.video_row(video)})


class AdminVideoPreviewView(APIView):
    """GET /api/admin/videos/{video_id}/preview — 등록한 영상이 실제로 나오는지.

    소비자 재생과 달리 상태·권한을 보지 않는다(playback.build_preview).
    **접근 통제는 이 기능 게이트 하나가 진다** — 서비스 쪽에는 게이트가 없다.
    """

    permission_classes = [FeatureRequired(FeatureKey.VIDEO_GRANT_ADMIN)]

    def get(self, request, video_id):
        video = video_admin.load_video(video_id)
        if video is None:
            return Response(
                {"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND
            )
        return Response(playback.build_preview(video, request.user, timezone.now()))


class AdminVideoCourseWeekListView(APIView):
    """GET /api/admin/videos/course-weeks — 등록 폼의 주차 선택지."""

    permission_classes = [FeatureRequired(FeatureKey.VIDEO_GRANT_ADMIN)]

    def get(self, request):
        return Response({"course_weeks": video_admin.course_week_rows()})

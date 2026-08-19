"""curriculum 뷰 — 캘린더 홈(2차) + 반 개설(FLOW 1-2·1-3).

- GET /api/student/home?month=YYYY-MM  로그인 학생 본인 홈 (IsStudent)
- GET /api/parent/home?student_id=&month=  자녀 홈 조회 (IsParent, 읽기 전용)
- GET·POST /api/admin/classes          반 목록 · 커리와 반 만들기 (계정관리)
- GET  /api/admin/classes/{id}         반 하나 — 주차와 명단
- POST·PATCH·DELETE .../sessions       반별 주차 추가 · 날짜 수정 · 삭제

페이로드 조립은 home.build_home_payload 공용 서비스가 담당한다 — 뷰는
역할 게이트·입력 검증·대상 학생 결정(학부모는 자녀 소유 검증)만 한다.
"""
import datetime

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.features import FeatureKey
from apps.accounts.models import Parent, ParentStudent, Student
from apps.accounts.permissions import FeatureRequired, IsParent, IsStudent

from . import class_admin
from .home import build_home_payload
from .models import Class, Subject

# 404 단일 메시지 — 타인 자녀·미존재를 구분해 주지 않는다(존재 비노출,
# 로그인 실패 단일 메시지와 같은 방향).
_NOT_FOUND_MESSAGE = "찾을 수 없습니다."
_MONTH_FORMAT_MESSAGE = "month 형식은 YYYY-MM 입니다."


def _parse_month(raw):
    """`YYYY-MM` 문자열 → (year, month). 형식 오류는 ValueError 전파."""
    parsed = datetime.datetime.strptime(raw, "%Y-%m")
    return parsed.year, parsed.month


class StudentHomeView(APIView):
    """GET /api/student/home — 로그인 학생 본인의 캘린더 홈."""

    permission_classes = [IsStudent]

    def get(self, request):
        raw_month = request.query_params.get("month")
        month = None
        if raw_month:
            try:
                month = _parse_month(raw_month)
            except ValueError:
                return Response(
                    {"detail": _MONTH_FORMAT_MESSAGE}, status=status.HTTP_400_BAD_REQUEST
                )
        student = Student.objects.select_related("user").filter(user=request.user).first()
        if student is None:
            # 학생 role 인데 students 행이 없는 예외 상태 — 닫힘으로 방어
            return Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)
        return Response(build_home_payload(student, month=month))


class ParentHomeView(APIView):
    """GET /api/parent/home — 자녀 캘린더 홈 + 결제·결석/동보 (읽기 전용).

    자녀 소유 검증: parent_students 에 연결된 자녀만 조회 가능. 밖의
    student_id 는 존재 여부와 무관하게 404 — 타인 자녀 존재를 노출하지
    않는다(PRD §4). student_id 생략 시 첫 자녀(student_id 오름차순 —
    /api/me children 드롭다운 순서와 동일).
    """

    permission_classes = [IsParent]

    def get(self, request):
        raw_month = request.query_params.get("month")
        month = None
        if raw_month:
            try:
                month = _parse_month(raw_month)
            except ValueError:
                return Response(
                    {"detail": _MONTH_FORMAT_MESSAGE}, status=status.HTTP_400_BAD_REQUEST
                )
        raw_student_id = request.query_params.get("student_id")
        student_id = None
        if raw_student_id:
            try:
                student_id = int(raw_student_id)
            except ValueError:
                return Response(
                    {"detail": "student_id가 올바르지 않습니다."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        parent = Parent.objects.filter(user=request.user).first()
        if parent is None:
            return Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)
        links = list(
            ParentStudent.objects.filter(parent=parent)
            .select_related("student__user")
            .order_by("student_id")
        )
        student = self._select_child(links, student_id)
        if student is None:
            return Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)
        return Response(build_home_payload(student, month=month, include_billing=True))

    @staticmethod
    def _select_child(links, student_id):
        """student_id 미지정 → 첫 자녀, 지정 → 소유 자녀 중 일치만(없으면 None)."""
        if student_id is None:
            return links[0].student if links else None
        for link in links:
            if link.student_id == student_id:
                return link.student
        return None


# --- 관리자: 커리 + 반 개설 (FLOW 1-2·1-3) --------------------------------


class AdminClassListView(APIView):
    """GET·POST /api/admin/classes — 반 목록 · 커리와 반 만들기 (계정관리).

    **커리와 반은 한 화면에서 만든다**(FLOW 1-2). 그래서 POST 하나가 둘 다
    받는다 — `course_id` 를 주면 이미 있는 커리에 반을 더하고, 안 주면
    `track`·`subject`·`course_name`·`total_weeks` 로 커리를 새로 만든다.
    `subject` 는 이름이라 없으면 만들어지고, `track` 은 값집합 밖이면 400 이다.
    GET 이 그 둘의 고를 값(`tracks`·`subjects`)을 같이 내린다.

    만들면 **커리 총주차만큼 회차가 개강일부터 주 단위로 채워진다**(FLOW 1-3).
    반의 주차는 별도 표가 아니라 `grades.ClassSession` 이고(주 1회라 주차 =
    회차 — FLOW 1-1), 커리 쪽 주차(`CourseWeek`)는 내용·영상이 붙는 자리라
    없으면 여기서 만들어 회차에 물린다.

    주차 날짜 수정·추가·삭제는 `AdminClassSessionView` 다.
    """

    permission_classes = [FeatureRequired(FeatureKey.ACCOUNT_ADMIN)]

    def get(self, request):
        return Response(
            {
                "courses": class_admin.list_courses(),
                "tracks": Subject.Track.values,
                "subjects": class_admin.list_subjects(),
            }
        )

    def post(self, request):
        body = request.data if isinstance(request.data, dict) else {}
        try:
            klass = class_admin.open_class(
                course_id=body.get("course_id"),
                course_name=body.get("course_name"),
                total_weeks=body.get("total_weeks"),
                track=body.get("track"),
                subject=body.get("subject"),
                name=body.get("name"),
                start_date=body.get("start_date"),
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(class_admin.class_block(klass), status=status.HTTP_201_CREATED)


def _load_class(class_id):
    """반 1건 + 커리. 없으면 None — 뷰가 404 로 바꾼다."""
    return Class.objects.select_related("course").filter(pk=class_id).first()


class AdminClassDetailView(APIView):
    """GET /api/admin/classes/{class_id} — 반 하나: 주차와 명단 (계정관리).

    주차 편집(FLOW 1-3)과 반 이동(FLOW 3-9)이 같은 자리에서 일어나므로 한 번에
    내린다.
    """

    permission_classes = [FeatureRequired(FeatureKey.ACCOUNT_ADMIN)]

    def get(self, request, class_id):
        klass = _load_class(class_id)
        if klass is None:
            return Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)
        return Response(class_admin.class_detail(klass))


class AdminClassSessionView(APIView):
    """반별 주차 — 추가 · 날짜 수정 · 삭제 (FLOW 1-3, 계정관리).

    - POST   /api/admin/classes/{class_id}/sessions            마지막 다음 주차를 더한다
    - PATCH  /api/admin/classes/{class_id}/sessions/{week_no}  {session_date} — 뒤가 따라 밀린다
    - DELETE /api/admin/classes/{class_id}/sessions/{week_no}  마지막 주차만, 기록 없을 때만

    셋 다 반의 주차 목록을 돌려준다 — 날짜 하나를 고치면 뒤가 전부 바뀌므로
    바뀐 줄만 내리면 화면이 서버와 갈린다.
    """

    permission_classes = [FeatureRequired(FeatureKey.ACCOUNT_ADMIN)]

    def post(self, request, class_id):
        return self._run(class_id, lambda klass: class_admin.add_week(klass))

    def patch(self, request, class_id, week_no):
        body = request.data if isinstance(request.data, dict) else {}
        return self._run(
            class_id,
            lambda klass: class_admin.move_week(klass, week_no, body.get("session_date")),
        )

    def delete(self, request, class_id, week_no):
        return self._run(class_id, lambda klass: class_admin.remove_week(klass, week_no))

    @staticmethod
    def _run(class_id, action):
        klass = _load_class(class_id)
        if klass is None:
            return Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)
        try:
            return Response({"sessions": action(klass)})
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

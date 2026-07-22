"""accounts 뷰 — 인증 3종 로그인·로그아웃·비밀번호 변경·CSRF (PRD §4).

세션 인증 전제. 쓰기 요청은 Django 기본 CSRF 계약(쿠키 csrftoken →
헤더 X-CSRFToken)을 따르며, 프런트는 GET /api/auth/csrf 로 쿠키를 먼저 받는다.
"""
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .features import effective_features
from .models import Parent, ParentStudent, Student, User
from .permissions import STAFF_ROLES, IsParent, IsStaffRole, IsStudent
from .serializers import LoginSerializer, PasswordChangeSerializer, user_summary

# 실패 사유(계정 없음/비밀번호 오류/비활성/역할 불일치)를 구분하지 않는 단일 메시지 —
# 경쟁사 정찰 등 계정 존재 탐색을 막는다(상태 기반 노출 원칙과 같은 방향).
_LOGIN_FAILED_MESSAGE = "아이디 또는 비밀번호가 올바르지 않습니다."


class RoleLoginView(APIView):
    """로그인 공통 구현 — 경로별 서브클래스가 allowed_roles 만 지정한다.

    상태코드 설계(존재 노출 최소화에 대한 판단):
    - 401 = 자격 오류(계정 없음·비밀번호 오류·비활성 — authenticate 가 전부 None).
    - 403 = 자격은 유효하나 이 경로의 역할군이 아님(로그인 미수립).
    - 두 경우 **메시지는 동일**하게 내려 계정 존재·역할을 응답 본문으로
      구분할 수 없게 한다. 상태코드 분리는 유지 — 프런트가 "다른 유형의
      로그인 페이지로 안내" 같은 UX 를 붙일지 선택할 수 있는 여지를 남기되,
      본문만 보는 스크래퍼에게는 추가 정보가 없다.
    """

    permission_classes = [AllowAny]
    allowed_roles: frozenset = frozenset()

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = authenticate(
            request,
            username=serializer.validated_data["login_id"],
            password=serializer.validated_data["password"],
        )
        # ModelBackend 는 is_active=False 를 인증 실패로 처리한다(차단 요구 충족).
        if user is None:
            return Response(
                {"detail": _LOGIN_FAILED_MESSAGE}, status=status.HTTP_401_UNAUTHORIZED
            )
        if user.role not in self.allowed_roles:
            return Response({"detail": _LOGIN_FAILED_MESSAGE}, status=status.HTTP_403_FORBIDDEN)
        login(request, user)
        return Response(user_summary(user))


class StudentLoginView(RoleLoginView):
    """POST /api/auth/login/student — 학생 역할만."""

    allowed_roles = frozenset({User.Role.STUDENT})


class ParentLoginView(RoleLoginView):
    """POST /api/auth/login/parent — 학부모 역할만."""

    allowed_roles = frozenset({User.Role.PARENT})


class AdminLoginView(RoleLoginView):
    """POST /api/auth/login/admin — 직원 역할군(대표·관리자·조교)."""

    allowed_roles = STAFF_ROLES


class LogoutView(APIView):
    """POST /api/auth/logout — 세션 종료. 비로그인 호출도 성공(멱등)."""

    permission_classes = [AllowAny]

    def post(self, request):
        logout(request)
        return Response({"detail": "로그아웃되었습니다."})


class PasswordChangeView(APIView):
    """POST /api/auth/password — 현재 비밀번호 검증 후 변경.

    - User.set_password 가 password_changed_at 을 갱신한다(모델 구현 확인됨).
      must_change_password 는 모델이 건드리지 않으므로 여기서 False 로 전환 —
      일괄생성 계정의 최초 로그인 변경 강제(PRD 3.1.5)가 이 지점에서 풀린다.
    - update_session_auth_hash 로 현재 세션을 유지한다(변경 직후 로그아웃 방지).
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = PasswordChangeSerializer(data=request.data, context={"user": request.user})
        serializer.is_valid(raise_exception=True)
        user = request.user
        user.set_password(serializer.validated_data["new_password"])
        user.must_change_password = False
        user.save(update_fields=["password", "password_changed_at", "must_change_password"])
        update_session_auth_hash(request, user)
        return Response({"detail": "비밀번호가 변경되었습니다.", "must_change_password": False})


class MeView(APIView):
    """GET /api/me — 상태 기반 노출의 관문(PRD §4, key_considerations §1).

    **프런트 화면·메뉴는 이 응답으로만 조립한다** — 하드코딩된 고정 목록 금지.

    - 공통: user_id·name·role·must_change_password
    - 학생: student{student_id, enrollment_status, grade, current_class}.
      enrollment_status 가 예비등록(미등록)이면 프런트는 bare 렌더(교재 구매만).
      students 행이 없는 예외 상태는 null 로 방어.
    - 학부모: children[] — 자녀 드롭다운 소스(parent_students 경유,
      student_id 오름차순). 자녀 이름은 연결된 users 행에서 취한다(미발급이면 null).
    - 직원(대표·관리자·조교): features[] = effective_features(user) —
      **관리자 메뉴 렌더 계약**. 프런트 메뉴는 이 목록으로만 조립하고,
      강제는 각 API 의 FeatureRequired 가 담당(프런트 숨김은 보조).

    역할 밖 블록은 응답에 포함하지 않는다(경쟁사 정찰 방지 — 기능 전모 비노출).
    권한은 세 역할군 게이트의 합집합 — 값집합 밖 유령 role 은 여기서 걸러진다.
    """

    permission_classes = [IsStudent | IsParent | IsStaffRole]

    def get(self, request):
        user = request.user
        data = user_summary(user)
        if user.role == User.Role.STUDENT:
            data["student"] = self._student_block(user)
        elif user.role == User.Role.PARENT:
            data["children"] = self._children_block(user)
        elif user.role in STAFF_ROLES:
            data["features"] = sorted(effective_features(user))
        return Response(data)

    @staticmethod
    def _student_block(user):
        student = Student.objects.filter(user=user).first()
        if student is None:
            return None
        return {
            "student_id": student.student_id,
            "enrollment_status": student.enrollment_status,
            "grade": student.grade,
            "current_class": student.current_class,
        }

    @staticmethod
    def _children_block(user):
        parent = Parent.objects.filter(user=user).first()
        if parent is None:
            return []
        links = (
            ParentStudent.objects.filter(parent=parent)
            .select_related("student__user")
            .order_by("student_id")
        )
        return [
            {
                "student_id": link.student.student_id,
                "name": link.student.user.name if link.student.user else None,
                "grade": link.student.grade,
            }
            for link in links
        ]


@method_decorator(ensure_csrf_cookie, name="dispatch")
class CsrfCookieView(APIView):
    """GET /api/auth/csrf — csrftoken 쿠키 발급(SPA 최초 진입 시 호출).

    Django 기본 계약 유지: 쿠키명 csrftoken, 헤더명 X-CSRFToken.
    (axios 기본값은 X-XSRF-TOKEN 이므로 프런트에서 헤더명 설정 필요 — 연동 메모 참조)
    """

    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"detail": "CSRF 쿠키가 발급되었습니다."})

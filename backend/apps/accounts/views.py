"""accounts 뷰 — 인증 3종(1차) + 관리자 운영(8차, PRD §4·3.1.5).

1차: 로그인 3종·로그아웃·비밀번호 변경·CSRF·/me. 세션 인증 전제. 쓰기 요청은
Django 기본 CSRF 계약(쿠키 csrftoken → 헤더 X-CSRFToken)을 따르며, 프런트는
GET /api/auth/csrf 로 쿠키를 먼저 받는다.

8차(관리자 운영 — admin_urls.py 마운트):
- GET/POST /api/admin/staff                    권한 매트릭스·직원 생성 (대표 전용)
- PUT      /api/admin/staff/{id}/features      기능 delta upsert (대표 전용)
- PATCH    /api/admin/staff/{id}/deactivate    직원 비활성 (대표 전용)
- POST     /api/admin/accounts/bulk            계정 일괄 발급 (계정관리)
- POST     /api/admin/accounts/{id}/register   예비등록→등록 전환 (계정관리)

게이트·입력 검증·상태 코드만 여기서, DB 쓰기·페이로드 조립은 staff_admin·
provisioning 서비스가 담당한다(attendance_admin 선례).
"""
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import provisioning, staff_admin
from .features import FeatureKey, effective_features
from .models import Parent, ParentStudent, Student, User
from .permissions import (
    STAFF_ROLES,
    FeatureRequired,
    IsOwner,
    IsParent,
    IsStaffRole,
    IsStudent,
)
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


# --- 관리자 운영(8차) — 권한 매트릭스·직원 계정 (대표 전용) ----------------

_NOT_FOUND_MESSAGE = "찾을 수 없습니다."


def _load_managed_staff(user_id):
    """매트릭스 관리 대상(관리자·조교) 로드 — (user, error_response).

    - 없는 user_id → 404.
    - 대표 → 400(대상 변경 금지 — 대표는 전권 고정, 매트릭스 행이 아님).
    - 학생·학부모 → 404(직원 아님 — 존재를 특정하지 않는다).
    """
    target = User.objects.filter(pk=user_id).first()
    if target is None:
        return None, Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)
    if target.role == User.Role.OWNER:
        return None, Response(
            {"detail": "대표 계정은 변경 대상이 아닙니다."}, status=status.HTTP_400_BAD_REQUEST
        )
    if target.role not in staff_admin.MANAGED_ROLES:
        return None, Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)
    return target, None


class StaffMatrixView(APIView):
    """GET·POST /api/admin/staff — 매트릭스 조회·직원 계정 생성 (대표 전용)."""

    permission_classes = [IsOwner]

    def get(self, request):
        return Response(staff_admin.build_matrix())

    def post(self, request):
        body = request.data if isinstance(request.data, dict) else {}
        name = body.get("name")
        phone = body.get("phone")
        role = body.get("role")
        if not (isinstance(name, str) and name.strip()):
            return Response({"detail": "name이 필요합니다."}, status=status.HTTP_400_BAD_REQUEST)
        if not (isinstance(phone, str) and phone.strip()):
            return Response({"detail": "phone이 필요합니다."}, status=status.HTTP_400_BAD_REQUEST)
        if role not in staff_admin.MANAGED_ROLES:
            # 대표 계정은 이 API 로 만들지 않는다(대표 전용 기능의 자기 증식 차단).
            return Response(
                {"detail": "role은 관리자 또는 조교여야 합니다."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        user, initial_password = staff_admin.create_staff(name.strip(), phone.strip(), role)
        if user is None:
            return Response(
                {"detail": "이미 사용 중인 전화번호(아이디)입니다."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        payload = staff_admin.matrix_row(user)
        payload["initial_password"] = initial_password
        return Response(payload, status=status.HTTP_201_CREATED)


class StaffFeaturesView(APIView):
    """PUT /api/admin/staff/{user_id}/features — 기능 delta upsert (대표 전용)."""

    permission_classes = [IsOwner]

    def put(self, request, user_id):
        if request.user.pk == user_id:
            # 자기 자신 대상 금지 — 대표 스스로의 권한 축소·조작 실수 방지.
            return Response(
                {"detail": "자기 자신의 권한은 변경할 수 없습니다."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        target, error = _load_managed_staff(user_id)
        if error is not None:
            return error
        feature_map = request.data
        if not isinstance(feature_map, dict) or not feature_map:
            return Response(
                {"detail": "요청 본문은 {기능키: bool} 맵이어야 합니다."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        for key, value in feature_map.items():
            # 기능 키는 개방 값집합(StaffFeatureGrant 계약) — enum 밖 키도
            # 형식만 맞으면 통과시킨다(키 추가 시 무마이그레이션·무배포 원칙).
            if not (isinstance(key, str) and key.strip() and len(key) <= 50):
                return Response(
                    {"detail": "기능 키가 올바르지 않습니다."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if not isinstance(value, bool):
                return Response(
                    {"detail": "부여 값은 true/false여야 합니다."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        return Response(staff_admin.apply_feature_map(target, feature_map, request.user))


class StaffDeactivateView(APIView):
    """PATCH /api/admin/staff/{user_id}/deactivate — is_active=false (대표 전용).

    직원 퇴사는 실삭제가 아니라 비활성(StaffFeatureGrant 모델 계약 —
    이력·FK 보존). ModelBackend 가 is_active=false 로그인을 차단한다.
    """

    permission_classes = [IsOwner]

    def patch(self, request, user_id):
        target, error = _load_managed_staff(user_id)
        if error is not None:
            return error
        target.is_active = False
        target.save(update_fields=["is_active"])
        return Response(staff_admin.matrix_row(target))


class AccountBulkIssueView(APIView):
    """POST /api/admin/accounts/bulk — 학생 명단 일괄 발급 (계정관리).

    본문은 행 리스트(출결 PUT 선례). 행 내부 오류(중복·누락)는 400 이 아니라
    **행 단위 실패 리포트**로 나간다 — 형식 오류(리스트 아님·빈 명단)만 400.
    초기 비밀번호는 응답으로 1회 반환(임시 정책 — provisioning 모듈 docstring).
    """

    permission_classes = [FeatureRequired(FeatureKey.ACCOUNT_ADMIN)]

    def post(self, request):
        rows = request.data
        if not isinstance(rows, list) or not rows:
            return Response(
                {"detail": "요청 본문은 학생 명단 리스트여야 합니다."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(provisioning.bulk_issue(rows))


class AccountRegisterView(APIView):
    """POST /api/admin/accounts/{student_id}/register — 등록 전환 (계정관리)."""

    permission_classes = [FeatureRequired(FeatureKey.ACCOUNT_ADMIN)]

    def post(self, request, student_id):
        student = Student.objects.filter(pk=student_id).first()
        if student is None:
            return Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)
        try:
            provisioning.register_student(student)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            {
                "student_id": student.student_id,
                "enrollment_status": student.enrollment_status,
                "registered_at": timezone.localtime(student.registered_at).isoformat(),
            }
        )


@method_decorator(ensure_csrf_cookie, name="dispatch")
class CsrfCookieView(APIView):
    """GET /api/auth/csrf — csrftoken 쿠키 발급(SPA 최초 진입 시 호출).

    Django 기본 계약 유지: 쿠키명 csrftoken, 헤더명 X-CSRFToken.
    (axios 기본값은 X-XSRF-TOKEN 이므로 프런트에서 헤더명 설정 필요 — 연동 메모 참조)
    """

    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"detail": "CSRF 쿠키가 발급되었습니다."})

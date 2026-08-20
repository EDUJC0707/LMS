"""accounts 뷰 — 인증(1차·2026-07-28 개편) + 관리자 운영(8차, PRD §4·3.1.5).

인증: 소비자 통합 로그인(`/api/auth/login` — 학생·학부모)·직원 로그인
(`/api/auth/login/admin`)·로그아웃·비밀번호 변경·CSRF·/me. 세션 인증 전제. 쓰기 요청은
Django 기본 CSRF 계약(쿠키 csrftoken → 헤더 X-CSRFToken)을 따르며, 프런트는
GET /api/auth/csrf 로 쿠키를 먼저 받는다.

8차(관리자 운영 — admin_urls.py 마운트):
- GET/POST /api/admin/staff                    권한 매트릭스·직원 생성 (대표 전용)
- PUT      /api/admin/staff/{id}/features      기능 delta upsert (대표 전용)
- PATCH    /api/admin/staff/{id}/deactivate    직원 비활성 (대표 전용)
- PATCH    /api/admin/staff/{id}/activate      직원 재활성 (대표 전용)
- POST     /api/admin/accounts/bulk            계정 일괄 발급 (계정관리)
                                               본문 {class_id, rows} — 반은 조교가 고른다(FLOW 2-1)
- POST     /api/admin/accounts/{id}/register   예비등록→등록 전환 (계정관리)
- POST     /api/admin/accounts/{user_id}/password  임시 비밀번호 재발급 (계정관리)
- GET      /api/admin/students                 학생 명부 조회 (직원 공통)
- GET/PATCH /api/admin/students/{id}          학생 상세·수정 (계정관리)
- GET/POST /api/admin/aliases                  별칭표 조회·추가 (계정관리 — FLOW 2-2)
- PATCH/DELETE /api/admin/aliases/{table}/{id} 붙는 값 고치기·지우기 (계정관리)

게이트·입력 검증·상태 코드만 여기서, DB 쓰기·페이로드 조립은 staff_admin·
provisioning 서비스가 담당한다(attendance_admin 선례).
"""
from django.conf import settings
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.curriculum.models import Class, class_name_subquery

from . import provisioning, staff_admin, student_directory
from .aliases import COLUMN_FIELDS, alias_key
from .features import FeatureKey, effective_features
from .login_id import LoginIdError, nfc
from .models import ColumnAlias, Parent, ParentStudent, SchoolAlias, Student, User
from .permissions import (
    STAFF_ROLES,
    FeatureRequired,
    IsOwner,
    IsParent,
    IsStaffRole,
    IsStudent,
)
from .serializers import LoginSerializer, PasswordChangeSerializer, user_summary
from .throttling import THROTTLED_MESSAGE, client_ip, is_throttled, record_failure

# 실패 사유(계정 없음/비밀번호 오류/비활성/역할 불일치)를 구분하지 않는 단일 메시지 —
# 경쟁사 정찰 등 계정 존재 탐색을 막는다(상태 기반 노출 원칙과 같은 방향).
_LOGIN_FAILED_MESSAGE = "아이디 또는 비밀번호가 올바르지 않습니다."

# 퇴원으로 막힌 계정. **비밀번호가 맞았을 때만** 이 문구가 나간다(_is_withdrawn_login).
_WITHDRAWN_MESSAGE = "퇴원 처리된 계정입니다."

#: 랜딩(`hjcedu.com`)이 "이 사람 로그인돼 있나"를 **네트워크 호출 없이** 판단하는 표시.
#:
#: 세션 쿠키는 `HttpOnly` 라 JS 가 못 읽는다(그건 그대로 둔다 — 읽히면 탈취당한다).
#: 그래서 값 없는 표시 하나를 따로 발급한다. 랜딩은 `document.cookie` 에서 이것만
#: 보고 LMS 로 넘긴다. 서버에 물어보는 방식이면 응답을 기다리는 동안 랜딩이 한 번
#: 번쩍이고, 그 사이 사용자가 뭔가 누를 수도 있다.
#:
#: **값에 아무 의미도 담지 않는다.** 있으면 로그인, 없으면 아님. 위조해서 얻는 것은
#: LMS 로 튕겨 가는 것뿐이고, 거기엔 세션이 없으니 로그인 화면이 뜬다. 즉 이 쿠키는
#: 권한이 아니라 **힌트**다 — 권한 판정은 서버의 세션이 한다.
SIGNED_IN_COOKIE = "hjc_signed_in"


def _mark_signed_in(response):
    """로그인 표시를 켠다. 세션과 **같은 수명·같은 도메인**이어야 한다.

    수명이 어긋나면 세션은 죽었는데 표시만 남아, 랜딩이 LMS 로 보내고 거기서
    로그인 화면이 뜬다 — 사용자에겐 "눌렀더니 로그인하라네"로 보인다.
    """
    response.set_cookie(
        SIGNED_IN_COOKIE,
        "1",
        max_age=settings.SESSION_COOKIE_AGE,
        domain=settings.SESSION_COOKIE_DOMAIN,  # 운영은 `.hjcedu.com` — 랜딩도 읽어야 한다
        secure=settings.SESSION_COOKIE_SECURE,
        httponly=False,  # 랜딩 JS 가 읽어야 한다. 이 쿠키의 존재 이유가 이것이다
        samesite="Lax",
    )
    return response


def _clear_signed_in(response):
    """로그아웃 표시. `domain` 을 발급 때와 똑같이 줘야 실제로 지워진다."""
    response.delete_cookie(
        SIGNED_IN_COOKIE,
        domain=settings.SESSION_COOKIE_DOMAIN,
        samesite="Lax",
    )
    return response


class RoleLoginView(APIView):
    """로그인 공통 구현 — 경로별 서브클래스가 allowed_roles 만 지정한다.

    **역할 판정은 DB(users.role)** 다. 아이디 형식(학부모 `p` 접미사 등)은
    판정에 쓰지 않는다 — 아이디 규칙은 바뀌어도 권한은 바뀌면 안 되기 때문.

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
        login_id = serializer.validated_data["login_id"]
        ip = client_ip(request)

        # **authenticate 앞에서** 판정한다. 뒤에 두면 한도를 소진한 공격자가
        # 다음 시도에 비밀번호를 맞혔을 때 그대로 들어온다(throttling.py 참조).
        if is_throttled(login_id, ip):
            return Response(
                {"detail": THROTTLED_MESSAGE}, status=status.HTTP_429_TOO_MANY_REQUESTS
            )

        user = authenticate(
            request,
            username=login_id,
            password=serializer.validated_data["password"],
        )
        # ModelBackend 는 is_active=False 를 인증 실패로 처리한다(차단 요구 충족).
        if user is None:
            if _is_withdrawn_login(login_id, serializer.validated_data["password"]):
                # 자격이 맞는 사람이라 실패로 세지 않는다 — 여기서 429 를 얹으면
                # 사유를 말해 준 뜻이 없어진다(계속 다시 쳐 볼 이유가 없다).
                return Response(
                    {"detail": _WITHDRAWN_MESSAGE}, status=status.HTTP_401_UNAUTHORIZED
                )
            record_failure(login_id, ip)
            return Response(
                {"detail": _LOGIN_FAILED_MESSAGE}, status=status.HTTP_401_UNAUTHORIZED
            )
        if user.role not in self.allowed_roles:
            return Response({"detail": _LOGIN_FAILED_MESSAGE}, status=status.HTTP_403_FORBIDDEN)
        login(request, user)
        return _mark_signed_in(Response(user_summary(user)))


def _is_withdrawn_login(login_id, password):
    """퇴원으로 막힌 계정인가 — **비밀번호까지 맞아야** True.

    FLOW 3-4 는 "로그인 화면이 왜 안 되는지 말해 준다"를 요구한다. 아이디·
    비밀번호가 틀렸다고 하면 학생이 계속 다시 쳐 보고 조교에게 전화한다.

    **개인정보 판단**: 사유를 아이디만으로 가르면 "이 아이디가 우리 학생이었다"
    를 아무에게나 알려 주는 존재 확인 창구가 된다(단일 실패 문구를 둔 이유가
    그것이다). 그래서 **비밀번호 일치를 조건에 넣는다** — 여기까지 온 사람은
    이미 그 계정의 자격을 다 쥐고 있어서 새로 흘러가는 정보가 없다. 틀린
    비밀번호로는 퇴원생이든 아니든 똑같은 문구를 받는다.

    직원은 걸리지 않는다 — 퇴원은 학생·학부모의 사건이고, 비활성 직원
    계정에까지 이 문구를 붙이면 없던 존재 확인 창구가 다시 생긴다.
    """
    user = User.objects.filter(login_id=login_id).first()
    return (
        user is not None
        and not user.is_active
        and user.role in (User.Role.STUDENT, User.Role.PARENT)
        and user.check_password(password)
    )


class ConsumerLoginView(RoleLoginView):
    """POST /api/auth/login — 학생·학부모 공용 (2026-07-28 통합, PRD §4).

    학생과 학부모는 같은 화면·같은 링크로 들어온다(사용자 지시). 두 역할을
    경로로 가르지 않고 **users.role 로 판정**해 응답의 role 로 내려주면,
    프런트가 그 값으로 홈을 고른다. 아이디 규칙(학부모 `p` 접미사)은 판정
    근거로 쓰지 않는다 — 규칙은 바뀔 수 있고 DB 의 role 만이 권한의 준거다.

    직원은 이 경로로 들어오지 못한다(403) — 관리자 로그인은 별도 경로이며
    화면에 링크를 노출하지 않는다.
    """

    allowed_roles = frozenset({User.Role.STUDENT, User.Role.PARENT})


class AdminLoginView(RoleLoginView):
    """POST /api/auth/login/admin — 직원 역할군(대표·관리자·조교) 전용."""

    allowed_roles = STAFF_ROLES


class LogoutView(APIView):
    """POST /api/auth/logout — 세션 종료. 비로그인 호출도 성공(멱등)."""

    permission_classes = [AllowAny]

    def post(self, request):
        logout(request)
        return _clear_signed_in(Response({"detail": "로그아웃되었습니다."}))


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
      각 자녀의 enrollment_status 도 함께 내린다 — 학생 블록과 같은 축으로,
      예비등록·퇴원 자녀만 둔 학부모에게 성적·워크북 메뉴가 뜨지 않게
      프런트가 메뉴를 조립하는 근거(2026-07-28 보강, 모듈성 §1).
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
        student = (
            Student.objects.filter(user=user)
            .annotate(class_name=class_name_subquery())
            .first()
        )
        if student is None:
            return None
        return {
            "student_id": student.student_id,
            "enrollment_status": student.enrollment_status,
            "grade": student.grade,
            "current_class": student.class_name,
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
                "enrollment_status": link.student.enrollment_status,
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
        try:
            user, initial_password = staff_admin.create_staff(
                name.strip(), phone.strip(), role
            )
        except LoginIdError as exc:
            # 아이디를 만들 수 없는 입력(이름·번호 불량, 접미사 소진) — 사유를 그대로 전달.
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        if user is None:
            return Response(
                {"detail": "이미 사용 중인 아이디입니다."},
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


class StaffActivateView(APIView):
    """PATCH /api/admin/staff/{user_id}/activate — is_active=true (대표 전용).

    비활성의 역연산 — 매트릭스가 비활성 직원도 행으로 보여주는 이유가
    "재활성/이력 확인"(staff_admin.build_matrix 계약)인데 되돌릴 API 가 없어
    복직·오조작이 DB 직접 수정으로만 풀렸다(2026-07-28 보강).

    게이트는 deactivate 와 동일(IsOwner + _load_managed_staff) — 직원 계정
    관리는 대표 전용 민감 기능 후보이므로(key_considerations §2) 되돌리기만
    문턱을 낮추면 그 판단이 무너진다. 기능 권한 delta 는 건드리지 않는다
    (비활성 중에도 보존되므로 재활성 시 원래 권한이 그대로 살아난다).
    이미 활성인 계정에 호출해도 200(멱등 — 화면 재시도 안전).
    """

    permission_classes = [IsOwner]

    def patch(self, request, user_id):
        target, error = _load_managed_staff(user_id)
        if error is not None:
            return error
        target.is_active = True
        target.save(update_fields=["is_active"])
        return Response(staff_admin.matrix_row(target))


def _find_class(raw_class_id):
    """반 조회 — 값이 없거나 숫자가 아니면 None(뷰가 400 으로 옮긴다)."""
    try:
        class_id = int(raw_class_id)
    except (TypeError, ValueError):
        return None
    return Class.objects.select_related("course").filter(pk=class_id).first()


class AccountBulkIssueView(APIView):
    """POST /api/admin/accounts/bulk — 학생 명단 일괄 발급 (계정관리).

    본문은 `{class_id, rows}` 다. **반은 조교가 고른 것이지 파일에 있는 것이
    아니다**(FLOW 2-1) — 그래서 명단 밖에 따로 있고, 없으면 발급하지 않는다.
    반을 안 받던 시절에는 계정을 만들어도 그 학생이 어느 명단에도 뜨지 않았다.

    행 내부 오류(중복·누락)는 400 이 아니라 **행 단위 실패 리포트**로 나간다 —
    형식 오류(리스트 아님·빈 명단·반 미지정)만 400. 초기 비밀번호는 응답으로
    1회 반환(임시 정책 — provisioning 모듈 docstring).
    """

    permission_classes = [FeatureRequired(FeatureKey.ACCOUNT_ADMIN)]

    def post(self, request):
        body = request.data if isinstance(request.data, dict) else {}
        rows = body.get("rows")
        if not isinstance(rows, list) or not rows:
            return Response(
                {"detail": "요청 본문은 반(class_id)과 학생 명단(rows)이어야 합니다."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        klass = _find_class(body.get("class_id"))
        if klass is None:
            return Response(
                {"detail": "반을 선택해 주세요."}, status=status.HTTP_400_BAD_REQUEST
            )
        return Response(provisioning.bulk_issue(rows, klass))


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


class AccountPasswordResetView(APIView):
    """POST /api/admin/accounts/{user_id}/password — 임시 비밀번호 재발급 (계정관리).

    **잊으면 사람이 되돌린다**(FLOW 2-4) — 학생·학부모가 스스로 복구하는 길은
    두지 않았고, 그동안 되돌릴 수단도 Django admin 수퍼유저뿐이었다.

    대상은 **학생·학부모뿐**이다. 직원은 404 로 막는다 — 계정관리 키를 받은
    조교가 대표 비밀번호를 갈아 끼우고 그 계정으로 들어가는 길을 열지 않는다
    (직원 계정 관리는 대표 전용 — staff_admin 모듈 docstring). 없는 대상과
    같은 404 로 답하는 것은 존재를 특정하지 않기 위해서다.
    """

    permission_classes = [FeatureRequired(FeatureKey.ACCOUNT_ADMIN)]
    RESETTABLE_ROLES = frozenset({User.Role.STUDENT, User.Role.PARENT})

    def post(self, request, user_id):
        target = User.objects.filter(pk=user_id).first()
        if target is None or target.role not in self.RESETTABLE_ROLES:
            return Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)
        password = provisioning.reset_password(target)
        return Response(
            {
                "user_id": target.user_id,
                "login_id": target.login_id,
                "name": target.name,
                "initial_password": password,
            }
        )


class StudentDetailView(APIView):
    """GET·PATCH /api/admin/students/{student_id} — 학생 상세·수정 (계정관리).

    **고칠 자리가 여기 하나뿐이다**(FLOW 2-6). 번호가 한 자리 틀리게 들어온
    학생은 계속 남의 번호로 문자·청구를 받고, 아이디·대조키도 그 번호에서 나온
    채 남는다 — 지금까지 남은 수단은 지우고 다시 발급하는 것뿐이었고 그러면
    출결·성적이 딸려 나갔다.

    게이트가 목록(`StudentDirectoryView` — 직원 공통)과 다른 이유: 이 응답은
    **연락처를 싣고** 수정은 아이디·비밀번호를 다시 만든다. 명단 입력·계정
    발급과 같은 일이므로 같은 기능 키(`계정관리`)를 쓴다.

    PATCH 는 **보낸 필드만** 고친다(부분 수정). 값은 문자열만 받는다 — 숫자로
    온 전화번호는 앞자리 `0` 이 이미 떨어진 값이라 되살릴 수 없다.
    """

    permission_classes = [FeatureRequired(FeatureKey.ACCOUNT_ADMIN)]
    EDITABLE = ("name", "school", "grade", "phone", "parent_phone")

    def get(self, request, student_id):
        student = _load_student_or_404(student_id)
        if isinstance(student, Response):
            return student
        return Response(student_directory.detail(student))

    def patch(self, request, student_id):
        student = _load_student_or_404(student_id)
        if isinstance(student, Response):
            return student
        body = request.data if isinstance(request.data, dict) else {}
        fields = {key: body[key] for key in self.EDITABLE if key in body}
        if not fields:
            return Response(
                {"detail": "고칠 값이 없습니다."}, status=status.HTTP_400_BAD_REQUEST
            )
        if not all(isinstance(value, str) for value in fields.values()):
            return Response(
                {"detail": "값은 문자열이어야 합니다."}, status=status.HTTP_400_BAD_REQUEST
            )
        try:
            reissued = provisioning.update_student(student, **fields)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        student.refresh_from_db()
        return Response({**student_directory.detail(student), **reissued})


def _load_student_or_404(student_id):
    """학생 행 또는 404 응답 — 상세·수정이 같은 조회를 쓴다."""
    student = Student.objects.select_related("user").filter(pk=student_id).first()
    if student is None:
        return Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)
    return student


class StudentDirectoryView(APIView):
    """GET /api/admin/students — 학생 명부 조회 (직원 공통, 페이지네이션).

    권한이 기능 키가 아니라 역할 게이트(IsStaffRole)인 근거는
    student_directory 모듈 docstring 참조 — 워크북 업로드 대상 선택(조교)과
    등록 전환 대상 찾기(계정관리자)가 같은 조회를 쓰므로 기능 키 하나로 묶으면
    한쪽이 막힌다. 응답은 이름·원번·학년·반·등록상태뿐(연락처 미노출).

    쿼리: q / enrollment_status / course_id / class_name / page.
    """

    permission_classes = [IsStaffRole]

    def get(self, request):
        params = request.query_params
        enrollment_status = (params.get("enrollment_status") or "").strip()
        if enrollment_status and enrollment_status not in Student.EnrollmentStatus.values:
            return Response(
                {"detail": "enrollment_status 값이 올바르지 않습니다(예비등록/등록/퇴원)."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        raw_course_id = (params.get("course_id") or "").strip()
        course_id = None
        if raw_course_id:
            try:
                course_id = int(raw_course_id)
            except ValueError:
                return Response(
                    {"detail": "course_id가 올바르지 않습니다."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        queryset = student_directory.build_queryset(
            q=(params.get("q") or "").strip(),
            enrollment_status=enrollment_status,
            course_id=course_id,
            class_name=(params.get("class_name") or "").strip(),
        )
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        return paginator.get_paginated_response(
            [student_directory.row(student, student.class_name) for student in page]
        )


"""별칭표 두 개 — 표 이름 → (모델, 붙는 값이 들어가는 컬럼).

컬럼 별칭은 닫힌 값집합(열 키)에, 학교 별칭은 열린 데이터(정식 이름)에
붙지만 **화면에서는 같은 표 두 개**라 응답도 `{id, alias, target}` 하나로
맞춘다 — 붙는 값을 부르는 이름이 표마다 다르면 화면이 두 벌 필요해진다.
"""
_ALIAS_TABLES = {"컬럼": (ColumnAlias, "field"), "학교": (SchoolAlias, "canonical")}


def _alias_rows(table):
    model, target = _ALIAS_TABLES[table]
    return [
        {"id": pk, "alias": alias, "target": value}
        for pk, alias, value in model.objects.order_by("alias").values_list("pk", "alias", target)
    ]


def _clean_target(table, raw):
    """붙는 값 검증 — (값, 에러 응답) 중 하나만 채워 돌려준다."""
    target = nfc(raw).strip() if isinstance(raw, str) else ""
    if not target:
        return None, Response(
            {"detail": "붙일 이름을 골라 주세요."}, status=status.HTTP_400_BAD_REQUEST
        )
    if table == "컬럼" and target not in COLUMN_FIELDS:
        return None, Response(
            {"detail": "알 수 없는 열입니다."}, status=status.HTTP_400_BAD_REQUEST
        )
    return target, None


def _load_alias(table, alias_id):
    """표 이름 + id → 행. 표 이름이 틀렸거나 없는 행이면 (None, 응답)."""
    if table not in _ALIAS_TABLES:
        return None, Response(
            {"detail": "별칭표를 찾을 수 없습니다."}, status=status.HTTP_404_NOT_FOUND
        )
    row = _ALIAS_TABLES[table][0].objects.filter(pk=alias_id).first()
    if row is None:
        return None, Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)
    return row, None


class AliasListView(APIView):
    """GET·POST /api/admin/aliases — 별칭표 (계정관리).

    **한 번 잘못 붙이면 이후 모든 명단이 조용히 오염된다**(FLOW 5-1) — 표가
    전역이라 어느 학원 파일이든 같은 답을 쓴다. 그래서 보고 고치는 자리가
    있어야 하고, 이 API 가 그 화면의 뒤다.

    게이트는 이 표를 소비하는 계정 발급과 같은 `계정관리` 다 — 붙여넣기
    화면을 못 여는 사람이 그 화면이 쓰는 표를 고칠 이유가 없다.
    """

    permission_classes = [FeatureRequired(FeatureKey.ACCOUNT_ADMIN)]

    def get(self, request):
        return Response({"columns": _alias_rows("컬럼"), "schools": _alias_rows("학교")})

    def post(self, request):
        body = request.data if isinstance(request.data, dict) else {}
        table = body.get("table")
        if table not in _ALIAS_TABLES:
            return Response(
                {"detail": "별칭표를 찾을 수 없습니다."}, status=status.HTTP_400_BAD_REQUEST
            )
        # 저장하는 것은 대조되는 형태다 — 화면이 보여 주는 값과 실제로 맞춰
        # 보는 값이 갈리면 "표에 있는데 왜 안 맞나"가 된다(aliases.alias_key).
        alias = alias_key(body.get("alias"))
        if not alias:
            return Response(
                {"detail": "별칭을 적어 주세요."}, status=status.HTTP_400_BAD_REQUEST
            )
        target, error = _clean_target(table, body.get("target"))
        if error is not None:
            return error
        model, field = _ALIAS_TABLES[table]
        if model.objects.filter(alias=alias).exists():
            return Response(
                {"detail": "이미 있는 별칭입니다."}, status=status.HTTP_400_BAD_REQUEST
            )
        row = model.objects.create(alias=alias, **{field: target})
        return Response(
            {"id": row.pk, "alias": alias, "target": target}, status=status.HTTP_201_CREATED
        )


class AliasDetailView(APIView):
    """PATCH·DELETE /api/admin/aliases/{table}/{alias_id} — 고치기·지우기 (계정관리).

    **별칭 자체는 고치지 않는다.** 별칭을 바꾸는 것은 다른 머리줄을 붙이는
    것이지 이 줄을 고치는 것이 아니다 — 지우고 새로 넣는 것과 같은 일이라
    두 길을 두지 않는다. 고칠 것은 **어디에 붙느냐**뿐이다.

    지우기는 흔적을 남기지 않는다(FLOW 5-1 이 요구한 것은 고칠 자리이지
    이력이 아니다) — 잘못 붙인 별칭이 지워지면 그것이 있었다는 사실도, 그
    사이 들어온 명단이 무엇에 물들었는지도 남지 않는다.
    """

    permission_classes = [FeatureRequired(FeatureKey.ACCOUNT_ADMIN)]

    def patch(self, request, table, alias_id):
        row, error = _load_alias(table, alias_id)
        if error is not None:
            return error
        body = request.data if isinstance(request.data, dict) else {}
        target, error = _clean_target(table, body.get("target"))
        if error is not None:
            return error
        field = _ALIAS_TABLES[table][1]
        setattr(row, field, target)
        row.save(update_fields=[field])
        return Response({"id": row.pk, "alias": row.alias, "target": target})

    def delete(self, request, table, alias_id):
        row, error = _load_alias(table, alias_id)
        if error is not None:
            return error
        row.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


@method_decorator(ensure_csrf_cookie, name="dispatch")
class CsrfCookieView(APIView):
    """GET /api/auth/csrf — csrftoken 쿠키 발급(SPA 최초 진입 시 호출).

    Django 기본 계약 유지: 쿠키명 csrftoken, 헤더명 X-CSRFToken.
    (axios 기본값은 X-XSRF-TOKEN 이므로 프런트에서 헤더명 설정 필요 — 연동 메모 참조)
    """

    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"detail": "CSRF 쿠키가 발급되었습니다."})

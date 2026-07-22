"""DRF 권한 부품 — 역할군 게이트 + 기능 키 게이트 (PRD §4, key_considerations §1·§2).

후속 API 전체가 재사용하는 공통 부품이다.

- 역할군: `IsStudent` / `IsParent` / `IsStaffRole` — 로그인 3종 분리와 같은
  경계(학생 / 학부모 / 직원=대표·관리자·조교)를 API 레벨에서 강제한다.
- 기능 키: `FeatureRequired(feature_key)` — 직원 세부 기능은
  `features.effective_features(user)`(프리셋 ⊕ delta)가 유일 준거.
  강제는 여기(API 레벨)가 본선이고 프런트 메뉴 숨김은 보조다.

사용 예::

    class GradeUploadView(APIView):
        permission_classes = [FeatureRequired(FeatureKey.GRADE_PROCESSING)]

    class StudentHomeView(APIView):
        permission_classes = [IsStudent]
"""
from rest_framework.permissions import BasePermission

from .features import effective_features
from .models import User

# 직원 역할군 — User.is_staff property 와 같은 경계. 퍼미션에서 재사용.
STAFF_ROLES = frozenset({User.Role.OWNER, User.Role.ADMIN, User.Role.ASSISTANT})

# 자격 없음 응답 메시지 — 기능 존재를 특정하지 않는다(상태 기반 노출 원칙).
_DENIED_MESSAGE = "접근 권한이 없습니다."


class _RolePermission(BasePermission):
    """역할군 게이트 공통 구현 — allowed_roles 에 속한 로그인 사용자만 통과."""

    message = _DENIED_MESSAGE
    allowed_roles: frozenset = frozenset()

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.role in self.allowed_roles)


class IsStudent(_RolePermission):
    """학생 역할만 허용. 등록/미등록 세분화는 각 기능 API 의 자격 검사 몫."""

    allowed_roles = frozenset({User.Role.STUDENT})


class IsParent(_RolePermission):
    """학부모 역할만 허용."""

    allowed_roles = frozenset({User.Role.PARENT})


class IsStaffRole(_RolePermission):
    """직원 역할군(대표·관리자·조교)만 허용. 세부 기능은 FeatureRequired 로."""

    allowed_roles = STAFF_ROLES


class IsOwner(_RolePermission):
    """대표 역할만 허용 — 대표 전용 화면(권한 매트릭스·노쇼 해제 등)의 게이트.

    기능 키(FeatureRequired)가 아니라 **역할 게이트**다 — 권한 매트릭스는
    role=대표만 허용이 과제 명세(PRD §4·key_considerations §2)라서, 관리자가
    delta 로 `권한부여` 키를 받아도 이 게이트는 열리지 않는다. 대표 전용
    민감 기능 범위가 확정되면(OWNER_ONLY_FEATURES) 기능 키 축과의 통합을
    검토한다.
    """

    allowed_roles = frozenset({User.Role.OWNER})


def FeatureRequired(feature_key):  # noqa: N802 — 퍼미션 클래스 팩토리(클래스처럼 사용)
    """기능 키 게이트 팩토리 — `permission_classes = [FeatureRequired("성적처리")]`.

    - 대표는 전권 단락(DB 조회 없이 즉시 허용).
    - 관리자·조교는 effective_features(프리셋 ⊕ delta) 보유 시에만 허용.
    - 그 외(학생·학부모·비로그인)는 차단 — 닫힘이 기본값(key_considerations §5).
    """

    class _FeatureRequired(BasePermission):
        message = _DENIED_MESSAGE

        def has_permission(self, request, view):
            user = request.user
            if not (user and user.is_authenticated):
                return False
            if user.role == User.Role.OWNER:
                return True  # 대표 전권 단락
            if user.role not in STAFF_ROLES:
                return False
            return feature_key in effective_features(user)

    return _FeatureRequired

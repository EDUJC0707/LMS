"""직원 권한 매트릭스·직원 계정 서비스 — 대표 전용 (PRD §4, key_considerations §2).

**대표 전용 판단**: 직원 계정 생성/비활성·권한 부여는 key_considerations §2 의
"대표 전용 민감 기능" 후보이고, 과제 명세가 매트릭스 API 를 role=대표만으로
확정했다 — 강제는 permissions.IsOwner(역할 게이트, 기능 키 아님)가 담당한다.

**최소 delta 계약**: StaffFeatureGrant 는 프리셋과의 **편차만** 저장한다
(모델 docstring). 매트릭스 토글이 프리셋과 같은 값을 upsert 하면 delta 행을
지워 정리한다 — 프리셋 변경(코드 수정) 시 낡은 delta 가 의도치 않은 회수/부여로
남는 것을 막는 유일한 방법이 "편차 없는 행은 두지 않기"이기 때문.

뷰(views.py)는 게이트·입력 검증·상태 코드만, DB 쓰기·페이로드 조립은 여기가
담당한다(attendance_admin 선례).
"""
from django.db import IntegrityError, transaction

from .features import ROLE_PRESETS, FeatureKey, effective_features
from .models import StaffFeatureGrant, User
from .provisioning import generate_initial_password

# 매트릭스 관리 대상 역할 — 대표는 전권 고정이라 행 자체가 없다.
MANAGED_ROLES = (User.Role.ADMIN, User.Role.ASSISTANT)


def matrix_row(staff_user, deltas=None):
    """직원 1명의 매트릭스 행 — 프리셋/delta(추가·회수)/유효 기능 구분 표시.

    프런트 매트릭스 UI 가 "프리셋 기본값 vs 대표가 가감한 것"을 시각적으로
    구분해 렌더할 수 있게 세 축을 모두 내린다(유효 기능만으로는 복원 불가).
    """
    if deltas is None:
        deltas = list(staff_user.feature_grants.all())
    added = sorted(d.feature_key for d in deltas if d.is_granted)
    removed = sorted(d.feature_key for d in deltas if not d.is_granted)
    preset = ROLE_PRESETS.get(staff_user.role, frozenset())
    return {
        "user_id": staff_user.user_id,
        "login_id": staff_user.login_id,
        "name": staff_user.name,
        "role": staff_user.role,
        "is_active": staff_user.is_active,
        "preset": sorted(preset),
        "delta": {"added": added, "removed": removed},
        "effective": sorted(effective_features(staff_user)),
    }


def build_matrix():
    """GET 응답 본문 — 기능 키 전체(매트릭스 열) + 직원별 행.

    비활성 직원도 포함한다(is_active 로 구분) — 매트릭스는 계정 관리 화면을
    겸하므로 비활성 계정의 재활성/이력 확인이 가능해야 한다.
    """
    staff = (
        User.objects.filter(role__in=MANAGED_ROLES)
        .prefetch_related("feature_grants")
        .order_by("user_id")
    )
    return {
        "feature_keys": list(FeatureKey.values),
        "staff": [matrix_row(u) for u in staff],
    }


def apply_feature_map(target, feature_map, actor):
    """{feature_key: bool} 맵 upsert — 최소 delta 유지(모듈 docstring).

    - 원하는 값 == 프리셋 보유 여부 → delta 행 삭제(있으면).
    - 다르면 upsert(is_granted=원하는 값, granted_by=actor).
    한 트랜잭션 — 매트릭스 저장은 전량 반영되거나 전량 무효여야 한다.
    """
    preset = ROLE_PRESETS.get(target.role, frozenset())
    with transaction.atomic():
        for key, desired in feature_map.items():
            if desired == (key in preset):
                StaffFeatureGrant.objects.filter(user=target, feature_key=key).delete()
            else:
                StaffFeatureGrant.objects.update_or_create(
                    user=target,
                    feature_key=key,
                    defaults={"is_granted": desired, "granted_by": actor},
                )
    return matrix_row(target, deltas=list(target.feature_grants.all()))


def create_staff(name, phone, role):
    """직원 계정 생성 — login_id=전화번호(8-4 규칙과 동일 축)·랜덤 초기 비번.

    must_change_password 는 User 기본값(True) 그대로 — 최초 로그인 시 변경
    강제(PRD 3.1.5 와 동일 계약). 반환: (user, 초기 비밀번호) — 비밀번호는
    발급 응답에서 1회 노출(해시만 저장되므로 재조회 불가).
    login_id 중복은 None 반환(뷰가 400) — 사전 조회 + IntegrityError 이중 방어.
    """
    if User.objects.filter(login_id=phone).exists():
        return None, None
    password = generate_initial_password()
    try:
        with transaction.atomic():
            user = User.objects.create_user(
                login_id=phone, password=password, name=name, role=role, phone=phone
            )
    except IntegrityError:
        return None, None
    return user, password

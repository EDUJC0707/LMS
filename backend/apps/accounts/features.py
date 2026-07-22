"""직원 기능 권한 — 기능 키·역할 프리셋·유효 기능 산출 (2026-07-22 확정).

계약(PRD §4 "직원 기능 권한", key_considerations §1·§2):
- **기능 키는 코드가 정의**(이 모듈의 FeatureKey), **부여는 DB**
  (accounts.StaffFeatureGrant — 직원↔기능 키 delta).
- **유효 기능 = 역할 프리셋 ⊕ delta**(is_granted true=추가/false=회수).
  대표는 전권. 산출은 `effective_features(user)` 가 유일 준거.
- 강제는 API 레벨(퍼미션 클래스가 이 함수를 소비), 프런트는 서버가 내려주는
  보유 기능 목록으로 메뉴를 렌더(상태 기반 노출 원칙과 동일 메커니즘) —
  기능 단위 단계적 오픈·1차 범위 조정이 코드 수정 없이 가능해진다.
"""
from django.db import models

from .models import User


class FeatureKey(models.TextChoices):
    """직원 기능 키 — PRD 관리자 화면 지도 기준.

    개방 값집합(DB 에 CHECK·choices 바인딩 없음 — notifications.type 선례).
    키 추가 = 여기 상수 추가뿐(무마이그레이션). 값은 한국어(설계 원칙).
    """

    GRADE_PROCESSING = "성적처리", "성적처리"  # 3.1.1 OMR 채점·보정·성적표 배부
    ATTENDANCE_ENTRY = "출결입력", "출결입력"  # 3.1.6 출결 SSOT 입력·퇴원 처리
    VIDEO_GRANT_ADMIN = "영상지급관리", "영상지급관리"  # 3.1.3·3.1.4 업로드·권한 지급/회수
    CLINIC_ASSIGN = "클리닉배정", "클리닉배정"  # 3.2.4 승인·배정·수행·평가
    PAYMENT_CHECK = "결제확인", "결제확인"  # 3.1.5 결제 내역·배부 상태
    NOTICE_WRITE = "공지작성", "공지작성"  # 3.3.1 공지·주차공지 게시
    COUNSEL_RECORD = "상담기록", "상담기록"  # 3.1.9 결석·학부모 상담 기록
    NOTIFICATION_SEND = "알림발송", "알림발송"  # 3.1.2 알림 발송·발송내역 조회
    WORKBOOK_UPLOAD = "워크북업로드", "워크북업로드"  # 3.1.7 워크북 사진 업로드
    QUESTION_BANK_ADMIN = "문제은행관리", "문제은행관리"  # 3.1.8 문제은행·유사문항 매칭
    ACCOUNT_ADMIN = "계정관리", "계정관리"  # 3.1.5 명단 입력·계정 발급·등록 처리
    FEATURE_GRANT_ADMIN = "권한부여", "권한부여"  # PRD §4 권한 매트릭스(대표 전용 후보)


# 대표 전용 민감 기능 — **범위는 추후 결정**(key_considerations §2: 권한 부여·직원
# 계정 관리·클리닉 컷값/노쇼 해제·성적 정정 승인·결제 취소/환불이 후보). 자리만
# 만들고 값은 비워둔다. 확정 시 여기 채우면 effective_features 소비자(퍼미션
# 클래스)가 대표 외 보유를 차단하는 축으로 쓴다.
OWNER_ONLY_FEATURES: frozenset[str] = frozenset()

# 역할 프리셋(PRD 2장 역할 정의 기준). delta(StaffFeatureGrant)의 기준선.
ROLE_PRESETS: dict[str, frozenset[str]] = {
    # 관리자 = 운영 전반(성적·출결·영상·결제·공지·상담 등 — PRD 2장).
    # 권한부여만 제외 — 대표 전용 후보(key_considerations §2)라 기본 미부여,
    # 필요 시 대표가 개별 delta 로만 연다.
    User.Role.ADMIN: frozenset(
        {
            FeatureKey.GRADE_PROCESSING,
            FeatureKey.ATTENDANCE_ENTRY,
            FeatureKey.VIDEO_GRANT_ADMIN,
            FeatureKey.CLINIC_ASSIGN,
            FeatureKey.PAYMENT_CHECK,
            FeatureKey.NOTICE_WRITE,
            FeatureKey.COUNSEL_RECORD,
            FeatureKey.NOTIFICATION_SEND,
            FeatureKey.WORKBOOK_UPLOAD,
            FeatureKey.QUESTION_BANK_ADMIN,
            FeatureKey.ACCOUNT_ADMIN,
        }
    ),
    # 조교 = 부여된 범위 내 보조 업무(워크북 사진 업로드·클리닉 배정/수행 정도
    # — PRD 2장). 나머지는 대표가 개별 delta 로 부여.
    User.Role.ASSISTANT: frozenset(
        {
            FeatureKey.WORKBOOK_UPLOAD,
            FeatureKey.CLINIC_ASSIGN,
        }
    ),
}


def effective_features(user) -> set[str]:
    """유효 기능 산출 — **프리셋 ⊕ delta**. API 퍼미션·메뉴 구성의 유일 준거.

    - 대표: 전권(FeatureKey 전체) — delta 무시.
    - 관리자·조교: 역할 프리셋에서 시작해 StaffFeatureGrant 를 적용
      (is_granted true=추가/false=회수). enum 밖 키도 그대로 통과시킨다
      (개방 값집합 — 키 추가 시 무마이그레이션).
    - 그 외(학생·학부모 등): 빈 집합 — 닫힘이 안전 기본값(key_considerations §5).
    """
    if user.role == User.Role.OWNER:
        return set(FeatureKey)
    preset = ROLE_PRESETS.get(user.role)
    if preset is None:
        return set()
    features: set[str] = set(preset)
    deltas = user.feature_grants.values_list("feature_key", "is_granted")
    for feature_key, is_granted in deltas:
        if is_granted:
            features.add(feature_key)
        else:
            features.discard(feature_key)
    return features

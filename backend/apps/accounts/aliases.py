"""별칭표 — 학원 파일의 낯선 이름을 우리가 아는 이름으로 (FLOW 2-2).

표는 둘이고 둘 다 전역이다(`ColumnAlias`·`SchoolAlias`). 학원별로 나누지
않는다 — `성명` 은 어디서 와도 이름이다.

    컬럼 별칭표    이름       ← 성명 · 학생이름 · 학생 성명 · …
    학교 별칭표    숙명여자고등학교 ← 숙명고 · 숙명여고 · 숙명 여고

`login_id.py`·`matching_key.py` 와 같은 결의 규칙 모듈이다 — 여기 있는 것은
질의와 문자열 규칙뿐이고, 쓰기(누가 무엇을 붙였나)는 뷰가 한다.

**전화번호 정규화는 여기 없다.** FLOW 2-2 가 같은 자리에서 말하지만 그 규칙은
이미 `login_id.normalize_phone` 에 있고 발급 경로가 전부 그걸 지난다.
"""
import re

from .login_id import nfc
from .models import ColumnAlias, SchoolAlias

#: 컬럼 별칭이 붙을 수 있는 열 — 코드가 정의하는 닫힌 값집합.
#: 발급 요청 본문(`/api/admin/accounts/bulk` 의 행 키)과 같은 축이라 영문이다.
COLUMN_FIELDS = ("name", "phone", "parent_phone", "grade", "school")

# 별칭 키에서 떼는 문자 — 공백·마침표·가운뎃점·밑줄·슬래시·괄호·하이픈.
_STRIP = re.compile(r"[\s.·_/()-]")


def alias_key(raw) -> str:
    """별칭 대조 키 — NFC 로 합치고 공백·구두점을 뗀 소문자.

    **`frontend/src/pages/admin/manage/paste.ts` 의 `squash()` 와 글자까지 같은
    값을 내야 한다.** 머리줄을 맞춰 보는 것은 프런트고 저장·조회는 여기라,
    두 규칙이 갈리면 조교가 방금 답한 별칭이 다음 파일에서 안 맞는다.
    """
    if not isinstance(raw, str):
        return ""
    return _STRIP.sub("", nfc(raw)).lower()


def column_map() -> dict[str, str]:
    """별칭 → 열 전부. 머리줄 한 줄을 맞추는 데 질의 한 번만 쓴다."""
    return dict(ColumnAlias.objects.values_list("alias", "field"))


def resolve_school(raw) -> str:
    """학교 이름 → 정식 이름. 모르는 학교는 **온 그대로** 돌려준다.

    모른다고 행을 세우거나 실패시키지 않는다 — 학교는 저장만 하고 계정 판정에
    쓰지 않으므로(FLOW 2-3) 막을 이유가 없고, FLOW 2-3 의 상태 네 갈래
    (생성·기존·확인필요·실패)에 "학교를 모르겠다" 가 들어갈 자리도 없다.
    나중에 별칭표에 붙이면 그 다음 명단부터 맞는다.
    """
    text = nfc(raw).strip() if isinstance(raw, str) else ""
    if not text:
        return ""
    canonical = (
        SchoolAlias.objects.filter(alias=alias_key(text))
        .values_list("canonical", flat=True)
        .first()
    )
    return canonical or text

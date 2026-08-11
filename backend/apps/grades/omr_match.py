"""지면에서 읽은 대조키 → 학생. 대조 6분기(PRD 3.1.1).

판정은 순수 함수(`resolve`)고 DB 는 후보를 가져오는 데만 쓴다 — 6분기 전부를
DB 없이 검사할 수 있다.

## 왜 파이썬에서 대조하나

카드에는 쌍자음·겹받침·ㅙㅞ 가 없어 `꽃님` 이 `곷님` 으로 들어온다. 양쪽을
`decode.fold_to_card()` 로 낮춰 비교해야 그 학생이 시험마다 불일치로 떨어지지
않는데, 그 변환은 SQL 로 못 쓴다. 명단이 수백 명이라 통째로 읽어 비교하는 편이
인덱스를 얹는 것보다 싸다.

# ponytail: 명단 전수 스캔. 수천 명을 넘으면 folded_key 컬럼을 파고 인덱스를 건다.

## 반쪽 키도 쓴다

이름만 읽히거나 전화만 읽히는 장이 실제로 나온다(65장 중 2장이 전화 미기입).
**전화 뒷4가 이름보다 잘 갈린다** — 1만 갈래로 고르게 퍼지는데 한국 이름은
김·이·박에 몰린다. 그래서 반쪽이라도 후보가 하나면 그대로 확정한다.
"""
from apps.accounts.models import Student

from .models import AnswerSheet
from .omr import decode

_MS = AnswerSheet.MatchStatus


def match_sheet(name, phone, roster=None):
    """읽은 이름·전화 → `(student | None, match_status)`.

    `roster` 를 주면 그것만 본다(배치 처리 시 명단을 한 번만 읽으려고).
    """
    if roster is None:
        roster = list(Student.objects.select_related("user").all())
    return resolve(roster, name, phone)


def resolve(roster, name, phone):
    """순수 판정 — DB 를 모른다. 6분기 전부 여기서 갈린다."""
    if not name and not phone:
        return None, _MS.INVALID

    folded_name = decode.fold_to_card(name) if name else None
    exact = _by_key(roster, folded_name, phone) if name and phone else []
    if len(exact) == 1:
        return exact[0], _MS.MATCHED
    if len(exact) > 1:
        # 동명이인 + 같은 뒷4. 지면에 접미사가 없어 **원리상** 못 가른다.
        return None, _MS.DUPLICATE

    partial = _by_half(roster, folded_name, phone)
    if not partial:
        return None, _MS.MISSING
    if name and phone:
        # 양쪽 다 읽혔는데 붙여 놓으면 아무도 아니다 — 한쪽을 잘못 읽었다.
        return None, _MS.MISMATCH
    if len(partial) == 1:
        return partial[0], _MS.PARTIAL
    return None, _MS.PARTIAL


def _by_key(roster, folded_name, phone):
    return [s for s in roster if _folded(s) == f"{folded_name}{phone}"]


def _by_half(roster, folded_name, phone):
    """이름만 / 전화만으로 좁힌 후보. 둘 다 있으면 각각 맞는 것을 합친다."""
    hits = []
    for student in roster:
        key = _folded(student)
        if folded_name and key.startswith(folded_name):
            hits.append(student)
        elif phone and key.endswith(phone):
            hits.append(student)
    return hits


def _folded(student):
    return decode.fold_to_card(student.matching_key or "")

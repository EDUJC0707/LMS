"""해석 계약 — 마킹된 자모·숫자를 이름과 전화 뒷4자리로.

**이미지를 모른다.** 판정이 끝난 결과(`{열: (칠해진 행, ...)}`)만 받는다 —
그래서 실물 스캔 없이 전수 검증할 수 있다.

카드 자모 순서는 유니코드 순서와 다르다(카드 초성 14개 = ㄱㄴㄷㄹㅁㅂㅅㅇㅈㅊㅋㅌㅍㅎ,
유니코드 초성 19개 = 쌍자음 포함). 그래서 매핑표를 명시한다 — 순서가 같을 거라
가정하면 조용히 다른 글자가 나온다.
"""
from . import decode


def name_marks(*slots):
    """`("ㄱ","ㅣ","ㅁ")` 같은 (초성, 중성, 종성) 묶음들 → `{열: (행,)}`.

    종성 없는 글자는 `""`, 안 쓴 글자칸은 통째로 생략한다.
    """
    marks = {}
    for index, (lead, vowel, tail) in enumerate(slots):
        base = index * 3
        if lead:
            marks[base + 1] = (decode.CARD_CONSONANTS.index(lead) + 1,)
        if vowel:
            marks[base + 2] = (decode.CARD_VOWELS.index(vowel) + 1,)
        if tail:
            marks[base + 3] = (decode.CARD_CONSONANTS.index(tail) + 1,)
    return marks


def phone_marks(digits):
    return {position: (int(digit),) for position, digit in enumerate(digits, start=1)}


def test_composes_a_three_syllable_name():
    """받침 없는 글자는 종성 열이 비어 있다 — 정상이다."""
    marks = name_marks(("ㄱ", "ㅣ", "ㅁ"), ("ㅎ", "ㅏ", ""), ("ㄴ", "ㅡ", "ㄹ"))

    assert decode.decode_name(marks) == "김하늘"


def test_composes_a_two_syllable_name_leaving_the_rest_blank():
    """네 칸을 다 쓰지 않는 이름이 대부분이다."""
    marks = name_marks(("ㅂ", "ㅏ", "ㄱ"), ("ㅁ", "ㅣ", "ㄴ"))

    assert decode.decode_name(marks) == "박민"


def test_reports_nothing_when_a_slot_has_a_vowel_but_no_leading_consonant():
    """반만 칠한 글자칸은 추측하지 않는다 — 사람이 본다."""
    marks = name_marks(("ㄱ", "ㅣ", "ㅁ"))
    del marks[1]  # 초성만 지운다

    assert decode.decode_name(marks) is None


def test_reports_nothing_when_a_column_has_two_marks():
    """한 열에 둘이 칠해졌으면 어느 자모인지 기계가 못 고른다."""
    marks = name_marks(("ㄱ", "ㅣ", "ㅁ"))
    marks[1] = (1, 5)

    assert decode.decode_name(marks) is None


def test_rejects_a_name_with_a_hole_in_the_middle():
    """3번 칸이 비었는데 4번 칸이 차 있으면 이름이 아니라 오마킹이다."""
    marks = name_marks(("ㄱ", "ㅣ", ""), ("ㅎ", "ㅏ", ""))
    fourth = name_marks(("ㄴ", "ㅡ", ""))  # 1번 칸 자리로 만든 뒤 4번 칸으로 옮긴다
    marks[10] = fourth[1]
    marks[11] = fourth[2]

    assert decode.decode_name(marks) is None


def test_decodes_four_phone_digits_including_a_leading_zero():
    """카드 안내가 "0 있는 경우에도 모두 마킹" 이라 앞자리 0 도 칠해진다."""
    assert decode.decode_phone(phone_marks("0501")) == "0501"


def test_reports_nothing_when_a_phone_position_is_unmarked():
    marks = phone_marks("0501")
    del marks[3]

    assert decode.decode_phone(marks) is None


def test_builds_the_matching_key_from_name_and_phone():
    """대조키 = `{이름}{뒷4}` — accounts.matching_key 와 같은 축이다."""
    assert decode.matching_key("김하늘", "0001") == "김하늘0001"


def test_has_no_matching_key_when_either_half_is_missing():
    assert decode.matching_key(None, "0001") is None
    assert decode.matching_key("김하늘", None) is None


def test_card_cannot_express_tense_consonants():
    """카드 자모집합에 ㄲㄸㅃㅆㅉ 과 겹받침이 없다 — 지면의 한계다.

    그런 이름은 학생이 근사 마킹을 할 수밖에 없으므로, 대조는 정규화 비교가
    필요하다. 여기서는 그 한계를 사실로 고정해 둔다.
    """
    for tense in "ㄲㄸㅃㅆㅉ":
        assert tense not in decode.CARD_CONSONANTS
    for compound in ("ㄳ", "ㄵ", "ㄶ", "ㄺ", "ㄻ", "ㄼ", "ㅄ"):
        assert compound not in decode.CARD_CONSONANTS


def test_folds_a_name_to_the_form_the_card_can_express():
    """대조용 정규화 — 쌍자음을 홑자음으로, 겹받침을 첫 자음으로 낮춘다.

    저장된 이름이 `꽃님` 이면 카드에는 `곷님` 으로 들어온다. 그대로 비교하면
    그 학생은 매번 불일치로 떨어진다.
    """
    assert decode.fold_to_card("꽃님") == "곷님"
    assert decode.fold_to_card("김하늘") == "김하늘"

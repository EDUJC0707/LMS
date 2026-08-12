"""마킹 → 뜻. **이미지를 모른다**(PRD 3.1.1).

판정이 끝난 결과(`{열: (칠해진 행, ...)}`)만 받아 이름·전화 뒷4자리를 만든다.
그래서 실물 스캔 없이 전수 검증할 수 있고, 표본계가 바뀌어도 이 모듈은 그대로다.

## 카드 자모 순서는 유니코드 순서가 아니다

카드 초성/종성 열은 **홑자음 14개**(ㄱㄴㄷㄹㅁㅂㅅㅇㅈㅊㅋㅌㅍㅎ)뿐이고, 유니코드
초성은 쌍자음을 포함한 19개다. 순서가 같을 거라 가정하면 **조용히 다른 글자가
나온다** — 그래서 매핑을 표로 명시하고, 유니코드 쪽 인덱스는 문자열에서 찾는다.

## 지면이 표현하지 못하는 이름이 있다

카드에 없는 자모: 쌍자음 초성 `ㄲㄸㅃㅆㅉ`, 겹받침 전부(`ㄳㄵㄶㄺㄻㄼㄽㄾㄿㅀㅄ`
과 `ㄲㅆ`), 모음 `ㅙㅞ`. 그런 이름의 학생은 **근사 마킹을 할 수밖에 없다** —
`꽃님` 은 카드에 `곷님` 으로 들어온다.

그래서 대조는 저장된 이름을 `fold_to_card()` 로 **카드가 표현할 수 있는 형태로
낮춘 뒤** 비교해야 한다. 안 그러면 그 학생은 시험마다 불일치로 떨어지고, 조교가
매번 같은 사람을 손으로 골라야 한다.

## 못 읽으면 None

반만 칠한 글자칸, 한 열에 둘 이상, 중간이 빈 글자칸 — 전부 None 이다.
추측해서 이름을 지어내면 엉뚱한 학생의 성적표가 된다(닫힘 기본값).
"""
#: 카드 초성·종성 열의 자모(1행부터). 두 열이 같은 목록을 쓴다.
CARD_CONSONANTS = "ㄱㄴㄷㄹㅁㅂㅅㅇㅈㅊㅋㅌㅍㅎ"
#: 카드 중성 열의 자모(1행부터). 홑모음 10 → 이중모음 4 → 복합모음 5 순이다.
CARD_VOWELS = "ㅏㅑㅓㅕㅗㅛㅜㅠㅡㅣㅐㅒㅔㅖㅘㅚㅝㅟㅢ"

#: 유니코드 한글 음절 조합용 순서 — 카드 순서와 다르므로 인덱스를 여기서 찾는다.
UNICODE_LEADS = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
UNICODE_VOWELS = "ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ"
UNICODE_TAILS = " ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ"

SYLLABLE_BASE = 0xAC00
VOWEL_SPAN = 28
LEAD_SPAN = 588

#: 지면이 표현하지 못하는 자모 → 학생이 대신 칠하게 되는 자모.
#: 쌍자음은 홑자음으로, 겹받침은 **첫 자음**으로 낮춘다.
CARD_FOLD = {
    "ㄲ": "ㄱ", "ㄸ": "ㄷ", "ㅃ": "ㅂ", "ㅆ": "ㅅ", "ㅉ": "ㅈ",
    "ㄳ": "ㄱ", "ㄵ": "ㄴ", "ㄶ": "ㄴ", "ㄺ": "ㄹ", "ㄻ": "ㄹ",
    "ㄼ": "ㄹ", "ㄽ": "ㄹ", "ㄾ": "ㄹ", "ㄿ": "ㄹ", "ㅀ": "ㄹ",
    "ㅄ": "ㅂ", "ㅙ": "ㅚ", "ㅞ": "ㅟ",
}

NAME_SLOTS = 4
PHONE_POSITIONS = 4
#: 성적 조사 카드 수험번호 칸 수. 우리가 쓰는 값은 뒤 4칸뿐이다(decode_survey_number).
SURVEY_NUMBER_POSITIONS = 5


def decode_name(marks):
    """`{열: (칠해진 행, ...)}` → 이름. 못 읽으면 None.

    열은 1부터 12, 글자칸 k(0부터)는 열 `3k+1`(초성) `3k+2`(중성) `3k+3`(종성)이다.
    """
    name = []
    for slot in range(NAME_SLOTS):
        lead = _single(marks, slot * 3 + 1, CARD_CONSONANTS)
        vowel = _single(marks, slot * 3 + 2, CARD_VOWELS)
        tail = _single(marks, slot * 3 + 3, CARD_CONSONANTS)
        if lead is _AMBIGUOUS or vowel is _AMBIGUOUS or tail is _AMBIGUOUS:
            return None
        if lead is None and vowel is None:
            if tail is not None:
                return None  # 종성만 칠한 칸 — 오마킹이다
            break  # 여기서부터 안 쓴 칸
        if lead is None or vowel is None:
            return None  # 반만 칠한 글자칸은 추측하지 않는다
        name.append(_compose(lead, vowel, tail))
    if not name:
        return None
    if _any_marked_beyond(marks, len(name)):
        return None  # 중간이 빈 이름 — 사람이 봐야 한다
    return "".join(name)


def decode_phone(marks):
    """`{자리: (칠해진 숫자, ...)}` → 뒷4자리 문자열. 못 읽으면 None.

    앞자리 0 도 칠해진다(카드 안내: "0 있는 경우에도 모두 마킹").
    """
    digits = []
    for position in range(1, PHONE_POSITIONS + 1):
        marked = marks.get(position, ())
        if len(marked) != 1:
            return None
        digit = marked[0]
        if not 0 <= digit <= 9:
            return None
        digits.append(str(digit))
    return "".join(digits)


def decode_survey_number(marks):
    """조사 카드 수험번호 `{자리: (칠해진 숫자, ...)}` → 뒷4자리. 못 읽으면 None.

    칸이 다섯인데 우리가 쓰는 값은 넷이다. 학생들은 전화 뒷4를 **오른쪽에 붙여**
    넣고 맨 왼쪽 칸은 0 을 칠하거나 비워 둔다(실물 6/12 94장 실측) — 그래서
    1번 자리는 읽되 값으로 쓰지 않는다. 2~5 중 하나라도 흐리면 None 이다.
    """
    digits = []
    for position in range(2, SURVEY_NUMBER_POSITIONS + 1):
        marked = marks.get(position, ())
        if len(marked) != 1 or not 0 <= marked[0] <= 9:
            return None
        digits.append(str(marked[0]))
    return "".join(digits)


def decode_score(marks):
    """조사 카드 점수 `{자리: (칠해진 숫자, ...)}` → 정수. 못 읽으면 None.

    10의 자리는 **비어 있어도 된다**(0 이라는 뜻이다) — 지면에 0 칸이 없고
    카드 예시가 `ex) 08점` 을 1의 자리 하나로만 보여 준다. 1의 자리는 반드시
    있어야 한다: 둘 다 비면 "0점"과 "안 썼다"가 구분되지 않는다.
    """
    ones = marks.get("일", ())
    if len(ones) != 1:
        return None
    tens = marks.get("십", ())
    if len(tens) > 1:
        return None
    return (tens[0] if tens else 0) * 10 + ones[0]


def matching_key(name, phone):
    """대조키 = `{이름}{뒷4}`. 한쪽이라도 없으면 None.

    `accounts.matching_key.build_matching_key` 와 같은 축이다 — 지면에서 온 값과
    저장된 값이 같은 규칙으로 만들어져야 대조가 성립한다.
    """
    if not name or not phone:
        return None
    return f"{name}{phone}"


def fold_to_card(text):
    """저장된 이름을 **카드가 표현할 수 있는 형태로** 낮춘다(대조 전 정규화).

    음절을 자모로 풀어 카드에 없는 것만 바꾸고 다시 합친다.
    """
    folded = []
    for character in text:
        decomposed = _decompose(character)
        if decomposed is None:
            folded.append(character)
            continue
        lead, vowel, tail = decomposed
        folded.append(
            _compose(
                CARD_FOLD.get(lead, lead),
                CARD_FOLD.get(vowel, vowel),
                CARD_FOLD.get(tail, tail) if tail else None,
            )
        )
    return "".join(folded)


# --- 내부 부품 --------------------------------------------------------------

#: 한 열에 둘 이상 칠해진 상태 — None(안 칠함)과 구분해야 한다.
_AMBIGUOUS = object()


def _single(marks, column, alphabet):
    """그 열에 칠해진 자모 하나. 안 칠했으면 None, 둘 이상이면 _AMBIGUOUS."""
    marked = marks.get(column, ())
    if not marked:
        return None
    if len(marked) != 1:
        return _AMBIGUOUS
    row = marked[0]
    if not 1 <= row <= len(alphabet):
        return _AMBIGUOUS
    return alphabet[row - 1]


def _compose(lead, vowel, tail):
    """자모 셋 → 음절 하나."""
    return chr(
        SYLLABLE_BASE
        + UNICODE_LEADS.index(lead) * LEAD_SPAN
        + UNICODE_VOWELS.index(vowel) * VOWEL_SPAN
        + (UNICODE_TAILS.index(tail) if tail else 0)
    )


def _decompose(character):
    """음절 하나 → (초성, 중성, 종성 또는 None). 한글 음절이 아니면 None."""
    offset = ord(character) - SYLLABLE_BASE
    if not 0 <= offset < 11172:
        return None
    tail_index = offset % VOWEL_SPAN
    vowel_index = (offset // VOWEL_SPAN) % 21
    lead_index = offset // LEAD_SPAN
    return (
        UNICODE_LEADS[lead_index],
        UNICODE_VOWELS[vowel_index],
        UNICODE_TAILS[tail_index] if tail_index else None,
    )


def _any_marked_beyond(marks, slots_used):
    """쓰인 글자칸 뒤에 칠해진 열이 남아 있나 — 중간이 빈 이름 검출."""
    return any(
        marks.get(column) for column in range(slots_used * 3 + 1, NAME_SLOTS * 3 + 1)
    )

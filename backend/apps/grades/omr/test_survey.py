"""성적 조사 카드 판독 계약 — 모의고사 자체채점 점수(카드 판형 주석 참조).

이 카드는 우리가 찍지 않는다. 모의고사와 함께 오고, 학생이 학교에서 본 점수를
스스로 적어 낸다. 답안 카드와 성명란 좌표는 같지만 **답란이 없고** 번호칸이
다섯이다.

실물 94장(2026-06-12 am/pm)으로 잰 것 — 픽스처는 실물을 커밋할 수 없어
합성이지만, 아래 수치는 그 94장에서 나온 사실이다:
- 마커 검출 94/94 · 판독 59 · 보류 35(마킹 없음 34 · 점수 판독 불가 1)
- 점수는 전량 32~50 에 들어왔다. 지면은 59 까지 표현할 수 있으므로 격자가
  어긋났다면 불가능한 값이 나왔을 것이다
- 수험번호가 읽힌 26장을 같은 날 답안 카드의 전화 뒷4와 대조: 21 일치 ·
  4 불일치. 불일치 4건은 **전부 두 자리 이상** 달라 오독이 아니라 학생이
  다른 번호를 쓴 것이다(한 자리 차이 0건)
"""
import cv2
import numpy as np

from . import card, decode, normalize, sheet
from .test_sheet import GLYPH_GREY, MARK_GREY, SCAN_SIZE, blank_card

FRAME = normalize.CardFrame(
    np.array(
        [[1525.0, 120.0], [1525.0, 2225.0], [115.0, 2225.0], [115.0, 120.0]],
        dtype=np.float64,
    )
)


def survey_card(score=None, name_marks=None, number=None, ink=MARK_GREY):
    """조사 카드 합성 — 점수·성명·수험번호를 원하는 대로 칠한다.

    `name_marks` 는 `{성명 열: 행}`, `number` 는 5칸 문자열(빈 칸은 공백).
    답란이 없는 지면이라 눈금이 성명칸에서 나온다 — 그래서 성명을 안 칠하면
    실물의 "백지" 장과 같은 상태가 된다.
    """
    image = blank_card()
    name_marks = name_marks or {}
    drawn = {}
    if score is not None:
        tens, ones = divmod(score, 10)
        drawn.update({("십", tens): ink} if tens else {})
        drawn[("일", ones)] = ink
    for key, (u, v) in card.survey_score_cells():
        _blot(image, u, v, drawn.get(key, GLYPH_GREY), (13, 8))
    for (column, row), (u, v) in card.name_cells():
        grey = ink if name_marks.get(column) == row else GLYPH_GREY
        _blot(image, u, v, grey, (15, 15))
    for (position, digit), (u, v) in card.survey_number_cells():
        wanted = None if number is None else number[position - 1]
        grey = ink if wanted not in (None, " ") and int(wanted) == digit else GLYPH_GREY
        _blot(image, u, v, grey, (13, 8))
    return image


def _blot(image, u, v, grey, axes):
    x, y = FRAME.to_source(u, v)
    cv2.ellipse(image, (int(round(x)), int(round(y))), axes, 0, 0, 360, grey, -1)


#: 이름 "김서연" — 열 1~9(세 글자 × 초·중·종성). 실물 이름 길이라 눈금이
#: 실제와 같은 조건에서 선다(read.field_scale 은 위 절반의 중앙값을 본다).
#: ㄱ1 ㅣ10 ㅁ5 · ㅅ7 ㅓ3 (종성 없음) · ㅇ8 ㅕ4 ㄴ2
SEOYEON = {1: 1, 2: 10, 3: 5, 4: 7, 5: 3, 7: 8, 8: 4, 9: 2}


def test_reads_the_self_reported_score():
    reading = sheet.read_survey(survey_card(score=46, name_marks=SEOYEON))

    assert reading.held is None
    assert reading.score == 46


def test_a_blank_tens_column_means_a_single_digit_score():
    """지면의 10의 자리에는 0 칸이 없다 — 안 칠하면 0 이다(카드 예시 `ex) 08점`)."""
    reading = sheet.read_survey(survey_card(score=8, name_marks=SEOYEON))

    assert reading.score == 8


def test_the_top_and_bottom_of_the_scale_survive():
    """1의 자리는 지면 순서가 1,2,…,9,0 이라 마지막 칸이 0 이다 — 행번호가 아니다."""
    assert sheet.read_survey(survey_card(score=50, name_marks=SEOYEON)).score == 50
    assert sheet.read_survey(survey_card(score=19, name_marks=SEOYEON)).score == 19


def test_an_unmarked_card_is_held_not_scored():
    """실물 94장 중 34장이 버블을 안 칠하고 손글씨만 남겼다.

    그 장을 통과시키면 눈금이 인쇄 잡음이 되고 판정 문턱이 그 45% 로 내려가
    **글리프가 마킹으로 승격된다** — 안 쓴 카드에서 점수가 나온다.
    """
    reading = sheet.read_survey(survey_card())

    assert reading.score is None
    assert reading.held == sheet.CARD_UNMARKED


def test_a_card_without_a_score_is_held():
    """조사 카드는 점수가 전부다 — 못 읽으면 답이 없는 것과 같다."""
    reading = sheet.read_survey(survey_card(name_marks=SEOYEON))

    assert reading.score is None
    assert reading.held == sheet.SCORE_UNREADABLE


def test_the_card_is_not_found_on_blank_paper():
    width, height = SCAN_SIZE

    reading = sheet.read_survey(np.full((height, width), 255, np.uint8))

    assert reading.held == sheet.CARD_NOT_FOUND


def test_the_number_field_gives_the_last_four_digits():
    """칸은 다섯이지만 값은 뒤 넷이다 — 학생은 전화 뒷4를 오른쪽에 붙여 넣는다."""
    reading = sheet.read_survey(survey_card(score=44, name_marks=SEOYEON, number="06969"))

    assert reading.phone == "6969"
    assert reading.matching_key == "김서연6969"


def test_a_left_padded_blank_slot_reads_the_same():
    """맨 왼쪽 칸을 비운 학생도 같은 값이 나와야 한다 — 실물에 둘 다 있었다."""
    reading = sheet.read_survey(survey_card(score=44, name_marks=SEOYEON, number=" 6969"))

    assert reading.phone == "6969"


def test_an_empty_number_field_does_not_hold_the_sheet():
    """실물에서 번호칸은 셋 중 하나만 채워져 있었다. 점수는 멀쩡하다."""
    reading = sheet.read_survey(survey_card(score=44, name_marks=SEOYEON))

    assert reading.held is None
    assert reading.score == 44
    assert reading.phone is None
    assert reading.matching_key is None


def test_score_decoding_refuses_a_double_marked_place():
    """두 칸이 칠해지면 어느 쪽이 진짜인지 기계가 못 가른다 — 조교가 본다."""
    assert decode.decode_score({"십": (4,), "일": (6, 7)}) is None
    assert decode.decode_score({"십": (3, 4), "일": (6,)}) is None


def test_score_decoding_refuses_a_missing_ones_place():
    """둘 다 비면 "0점"과 "안 썼다"가 구분되지 않는다."""
    assert decode.decode_score({}) is None
    assert decode.decode_score({"십": (4,)}) is None

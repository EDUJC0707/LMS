"""장 단위 판독 계약 — 이미지 한 장 → 답, 아니면 보류 사유.

지금까지 호출부가 손으로 조립했다. 특히 `{(문항, 선택지): 잉크}` 를
`{문항: {선택지: 잉크}}` 로 뒤집는 루프가 평가 스크립트마다 다시 쓰였다 —
같은 코드가 여러 벌 있으면 반드시 한쪽만 고치는 날이 온다.

**보류 사유를 구분해서 돌려준다.** 조교 화면에서 "카드를 못 찾음"과 "마킹을
못 믿겠음"은 할 일이 다르다 — 전자는 다시 스캔, 후자는 눈으로 확인이다.
"""
import cv2
import numpy as np

from . import card, normalize, sheet

SCAN_SIZE = (1651, 2335)
#: 카드 방향 순서(좌상·우상·우하·좌하) — 실측 마커 자리.
CARD_CORNERS = np.array(
    [[1525.0, 120.0], [1525.0, 2225.0], [115.0, 2225.0], [115.0, 120.0]],
    dtype=np.float64,
)
MARKS = (
    ((115.0, 120.0), (21, 18)),
    ((1525.0, 120.0), (36, 18)),
    ((1525.0, 2225.0), (36, 18)),
    ((115.0, 2225.0), (21, 18)),
)


def blank_card():
    """마커만 있는 합성 스캔 — 실측 톤(종이 255 · 마커 64)."""
    width, height = SCAN_SIZE
    image = np.full((height, width), 255, dtype=np.uint8)
    for (cx, cy), (w, h) in MARKS:
        x0, y0 = int(round(cx - w / 2)), int(round(cy - h / 2))
        image[y0 : y0 + h, x0 : x0 + w] = 64
    return image


#: 빈 칸에도 인쇄된 ①~⑤ 글리프가 있어 잉크가 남는다 — 실측 평균 31.6~47.0.
#: 표본은 평균을 재므로 균일한 연회색으로 대신한다(255-215 = 40, 실측 한가운데).
#: **이 값을 빼면 안 된다.** 티 없이 깨끗한 카드를 그리면 줄 기준선이 6 까지
#: 떨어져 "격자가 지면을 벗어났다"는 보호장치가 정상 장에서 발화한다 —
#: 합성 픽스처가 현실보다 깨끗해서 생기는 함정이다.
GLYPH_GREY = 215
MARK_GREY = 40


def marked_card(answers):
    """`{문항: 선택지}` 대로 칠한 카드. 나머지 칸에는 인쇄 글리프 잉크가 남는다."""
    image = blank_card()
    frame = normalize.CardFrame(CARD_CORNERS)
    for (question, choice), (u, v) in card.answer_cells():
        x, y = frame.to_source(u, v)
        centre = (int(round(x)), int(round(y)))
        grey = MARK_GREY if answers.get(question) == choice else GLYPH_GREY
        cv2.ellipse(image, centre, (13, 8), 0, 0, 360, grey, -1)
    return image


def test_reads_a_whole_sheet_from_one_call():
    """호출부가 조립하지 않는다 — 이미지와 문항 수만 준다."""
    answers = {question: (question % 5) + 1 for question in range(1, 17)}

    reading = sheet.read_sheet(marked_card(answers), question_count=16)

    assert reading.held is None
    assert reading.answers == {q: (c,) for q, c in answers.items()}


def test_holds_with_a_distinct_reason_when_the_card_is_not_found():
    """빈 종이는 "카드 없음"이다 — 다시 스캔하라는 뜻이고, 판독 실패와 다르다."""
    width, height = SCAN_SIZE

    reading = sheet.read_sheet(np.full((height, width), 255, np.uint8), question_count=16)

    assert reading.answers is None
    assert reading.held == sheet.CARD_NOT_FOUND


def test_holds_when_the_marks_cannot_be_trusted():
    """마커는 찾았는데 연필이 과반이 아니면 판독을 못 믿는다 — 사람이 본다."""
    reading = sheet.read_sheet(marked_card({}), question_count=16)

    assert reading.answers is None
    assert reading.held == sheet.MARKS_UNTRUSTED


def test_reads_only_the_questions_the_exam_actually_has():
    """카드는 20줄이지만 시험이 16문항이면 17~20 은 판정에 넣지 않는다.

    빈 줄을 함께 넘기면 장 중앙 lead 가 최대 11.6% 내려가고, 흐린 장에서
    인쇄 글리프가 답으로 승격된다(실측: 그렇게 유령답 3건이 났었다).
    """
    answers = {question: 3 for question in range(1, 17)}

    reading = sheet.read_sheet(marked_card(answers), question_count=16)

    assert set(reading.answers) == set(range(1, 17))


def test_rejects_a_question_count_the_card_cannot_hold():
    """카드에 없는 문항을 달라고 하면 조용히 넘어가지 않는다."""
    try:
        sheet.read_sheet(blank_card(), question_count=99)
    except ValueError as error:
        assert "99" in str(error)
    else:
        raise AssertionError("문항 수가 카드 범위를 넘으면 ValueError 여야 한다")

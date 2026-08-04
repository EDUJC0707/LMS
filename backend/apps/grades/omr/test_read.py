"""판정 계약 — 셀 농도에서 "이 문항에 무엇이 칠해졌나"를 정한다.

값집합·임계는 실물 65장(1040문항)에서 나왔다. 판정은 **절대 농도가 아니라
줄 안에서의 상대값**이다. 두 가지가 절대 임계를 못 쓰게 만든다:

- 인쇄된 ①~⑤ 글리프가 칸마다 잉크량이 다르다(빈칸 기준선 31.6 ~ 47.0)
- 연필 압력이 장마다 3배까지 차이 난다(장별 중앙 lead 48.8 ~ 154.5)

그래서 ①한 줄 안에서 나머지 넷을 기준선으로 삼고 ②그 lead 를 **그 장의**
전형적인 lead 와 견준다.
"""
import cv2
import numpy as np

from . import card, normalize, read

#: 실측 스캔과 같은 크기·마커 자리(카드 방향 순서: 좌상·우상·우하·좌하).
SCAN_SIZE = (1651, 2335)
CARD_CORNERS = np.array(
    [[1525.0, 120.0], [1525.0, 2225.0], [115.0, 2225.0], [115.0, 120.0]], dtype=np.float64
)


def row(**inks):
    """`c1=..., c2=...` 로 한 문항 다섯 칸을 적는다."""
    return {int(key[1:]): value for key, value in inks.items()}


def sheet(**questions):
    """`q1=row(...)` 로 한 장을 적는다."""
    return {int(key[1:]): value for key, value in questions.items()}


def uniform_sheet(marked_choice, lead, count=16):
    """전 문항이 같은 세기로 한 칸씩 칠해진 장."""
    def cells():
        return {
            choice: (30.0 + lead if choice == marked_choice else 30.0)
            for choice in range(1, 6)
        }

    return {question: cells() for question in range(1, count + 1)}


def test_reads_the_single_dark_cell_as_the_answer():
    readings = read.classify_answers(uniform_sheet(marked_choice=3, lead=120))

    assert readings == {question: (3,) for question in range(1, 17)}


def test_reports_a_flat_row_as_blank():
    """다섯 칸이 고르면 아무것도 안 칠한 것이다 — 제일 진한 칸을 답으로 삼지 않는다."""
    inks = uniform_sheet(marked_choice=3, lead=120)
    inks[7] = row(c1=30.0, c2=31.0, c3=29.0, c4=30.0, c5=32.0)

    readings = read.classify_answers(inks)

    assert readings[7] == ()
    assert readings[8] == (3,)


def test_reports_both_cells_when_a_second_one_is_also_dark():
    """X 로 지운 자리도 진하다 — 어느 쪽이 진짜인지 정하지 않고 둘 다 넘긴다.

    실물의 X 넷은 2등 높이가 85·102·120·142 였고 나머지 문항 전부는 35 이하였다.
    """
    inks = uniform_sheet(marked_choice=3, lead=120)
    inks[5] = row(c1=30.0, c2=30.0, c3=170.0, c4=130.0, c5=30.0)

    assert read.classify_answers(inks)[5] == (3, 4)


def test_accepts_a_faint_sheet_by_comparing_it_to_its_own_marks():
    """연필을 흐리게 쓴 장. 절대 임계로는 전 문항이 빈칸이 된다.

    실물에서 장별 중앙 lead 가 48.8 ~ 154.5 로 3배 갈렸다 — 흐린 장의 정상
    마킹(lead 45)은 복수 판정 기준(50)에도 못 미친다.
    """
    readings = read.classify_answers(uniform_sheet(marked_choice=2, lead=45))

    assert readings == {question: (2,) for question in range(1, 17)}


def blank_scan():
    width, height = SCAN_SIZE
    return np.full((height, width), 255, dtype=np.uint8)


def fill_bubble(image, frame, u, v, shade=30):
    """카드 정규좌표 자리에 칠해진 버블 하나를 그린다."""
    x, y = frame.to_source(u, v)
    cv2.ellipse(image, (int(round(x)), int(round(y))), (11, 9), 0, 0, 360, shade, -1)


def test_measures_ink_only_where_a_bubble_is_filled():
    """표본 자리가 셀 중심을 벗어나면 칠한 칸과 빈 칸이 안 갈린다."""
    frame = normalize.CardFrame(CARD_CORNERS)
    cells = dict(card.answer_cells())
    image = blank_scan()
    fill_bubble(image, frame, *cells[(4, 2)])

    inks = read.sample_cells(image, frame, card.answer_cells(), card.ANSWER_BUBBLE_RADIUS)

    assert inks[(4, 2)] > 200
    assert max(ink for key, ink in inks.items() if key != (4, 2)) < 5

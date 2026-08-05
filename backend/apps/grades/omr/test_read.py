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


def test_flags_a_faint_double_mark_below_the_absolute_floor():
    """흐린 장의 복수 마킹 — 절대 50 아래라도 그 장 눈금으로는 2등이 크다.

    실물 X 넷의 2등은 장 중앙 lead 의 0.93~1.17배였다. 같은 X 를 제일 흐린 장
    (중앙 lead 48.5)에 옮기면 2등은 ~45 로 절대 50 아래에 숨는다 — 절대 임계만
    쓰면 단일 확신 판정이 나가고 조교가 볼 증거가 사라진다.
    """
    inks = uniform_sheet(marked_choice=3, lead=48)
    inks[5] = row(c1=30.0, c2=30.0, c3=82.0, c4=74.0, c5=30.0)

    assert read.classify_answers(inks)[5] == (3, 4)


def test_keeps_the_absolute_floor_on_dark_sheets():
    """진한 장의 복수 마킹 — 장 눈금(0.65 x 150 ~ 98)에 못 미쳐도 절대 50 이면 잡는다.

    실물 X 하나는 2등이 절대 85 였다. 상대 기준만 쓰면 진한 장에서 문턱이 100
    근처로 올라가 이런 X 를 놓친다 — 절대 하한이 그걸 막는다.
    """
    inks = uniform_sheet(marked_choice=2, lead=150)
    inks[9] = row(c1=30.0, c2=185.0, c3=30.0, c4=115.0, c5=30.0)

    assert read.classify_answers(inks)[9] == (2, 4)


def test_glyph_ink_on_a_faint_sheet_stays_single():
    """흐린 장에서 문턱이 내려가도 인쇄 글리프 잉크는 복수로 안 잡힌다.

    비-X 1029문항의 상대 2등 최대는 0.47 이었다(⑤ 글리프가 제일 도드라진 장).
    그 천장을 그대로 흐린 장에 놓아도 문턱(0.65) 아래다.
    """
    inks = uniform_sheet(marked_choice=3, lead=60)
    inks[8] = row(c1=30.0, c2=30.0, c3=90.0, c4=30.0, c5=58.0)

    assert read.classify_answers(inks)[8] == (3,)


def scalar_sample_cells(image, frame, cells, radius):
    """벡터화 전의 원본 루프 — sample_cells 등가의 기준 구현.

    실물 65장 전수(잉크 6,500개)에서 벡터판과 바이트 단위로 일치함을 확인했다
    (2026-08-05). 여기서는 그 등가를 합성 이미지로 고정한다.
    """
    height, width = image.shape
    offsets = read._interior_offsets(radius)
    inks = {}
    for key, (u, v) in cells:
        total = 0.0
        for offset_u, offset_v in offsets:
            x, y = frame.to_source(u + offset_u, v + offset_v)
            column = min(max(int(round(x)), 0), width - 1)
            row = min(max(int(round(y)), 0), height - 1)
            total += image[row, column]
        inks[key] = 255.0 - total / len(offsets)
    return inks


def assert_bit_identical(actual, expected):
    assert list(actual) == list(expected)
    for key in expected:
        assert np.float64(actual[key]).tobytes() == np.float64(expected[key]).tobytes(), key


def test_vectorised_sampling_matches_the_scalar_loop_bit_for_bit():
    """전 픽셀 난수 장 + 뒤틀린 프레임 — 표본이 한 자리만 어긋나도 합이 갈린다."""
    rng = np.random.default_rng(20260805)
    width, height = SCAN_SIZE
    image = rng.integers(0, 256, size=(height, width), dtype=np.uint8)
    frame = normalize.CardFrame(CARD_CORNERS + rng.uniform(-40.0, 40.0, size=(4, 2)))

    assert_bit_identical(
        read.sample_cells(image, frame, card.answer_cells(), card.ANSWER_BUBBLE_RADIUS),
        scalar_sample_cells(image, frame, card.answer_cells(), card.ANSWER_BUBBLE_RADIUS),
    )


def test_vectorised_sampling_clips_out_of_frame_points_like_the_loop():
    """이미지 밖으로 나간 표본점도 루프판과 같은 가장자리 픽셀에 물린다."""
    rng = np.random.default_rng(7)
    image = rng.integers(0, 256, size=(60, 40), dtype=np.uint8)
    frame = normalize.CardFrame(
        np.array([[-30.0, -20.0], [70.0, -10.0], [65.0, 85.0], [-25.0, 75.0]])
    )
    cells = [((row, col), (col / 3.0, row / 3.0)) for row in range(4) for col in range(4)]

    assert_bit_identical(
        read.sample_cells(image, frame, cells, card.ANSWER_BUBBLE_RADIUS),
        scalar_sample_cells(image, frame, cells, card.ANSWER_BUBBLE_RADIUS),
    )

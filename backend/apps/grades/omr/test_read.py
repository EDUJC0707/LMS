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
    """벡터화 전의 셀 단위 루프 — sample_cells 등가의 기준 구현(쌍선형).

    벡터판이 (셀 x 표본점)을 한 번에 처리하면서도 표본점별 누적 순서를 지키는지
    고정한다. 표본이 한 자리만 어긋나거나 합산 순서가 바뀌면 마지막 비트가 갈린다.
    """
    height, width = image.shape
    offsets = read._interior_offsets(radius)
    totals = {key: 0.0 for key, _ in cells}
    for offset_u, offset_v in offsets:
        for key, (u, v) in cells:
            x, y = frame.to_source(u + offset_u, v + offset_v)
            column = min(max(int(np.floor(x)), 0), width - 2)
            row = min(max(int(np.floor(y)), 0), height - 2)
            fx = min(max(x - column, 0.0), 1.0)
            fy = min(max(y - row, 0.0), 1.0)
            totals[key] += (
                (1 - fx) * (1 - fy) * image[row, column]
                + fx * (1 - fy) * image[row, column + 1]
                + (1 - fx) * fy * image[row + 1, column]
                + fx * fy * image[row + 1, column + 1]
            )
    return {key: 255.0 - total / len(offsets) for key, total in totals.items()}


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


def glyph_noise_row(index):
    """마킹 없는 줄의 실측 잉크 모사 — 인쇄 글리프만으로 lead 4~11 이 남는다.

    **쌍선형 표본계 실측치다**(65장, 진짜 빈 줄 267개): lead 중앙값 4.8 · 최대
    11.7. 최근접 표본계에서 최대 32.5 로 보이던 것은 양자화 잡음이 얹힌 값이었다.
    열마다 글리프 잉크가 달라 1등은 5·2 번 칸에 쏠린다.
    """
    rows = (
        row(c1=33.0, c2=36.0, c3=34.0, c4=31.0, c5=42.0),
        row(c1=32.0, c2=38.0, c3=35.0, c4=30.0, c5=36.0),
        row(c1=34.0, c2=37.0, c3=39.0, c4=32.0, c5=38.0),
        row(c1=31.0, c2=35.0, c3=33.0, c4=34.0, c5=43.0),
    )
    return dict(rows[index % 4])


def test_holds_a_blank_sheet_instead_of_reading_glyph_noise():
    """빈 장은 보류다 — 잡음 중앙값을 기준 삼으면 전 문항이 답으로 읽힌다.

    실측: 실물 65장을 전부 빈 장으로 만들어 넣었더니 65장 모두에서 12~16문항이
    답으로 승격됐고, 승격된 선택지는 글리프 잉크가 무거운 순서였다.
    """
    inks = {question: glyph_noise_row(question) for question in range(1, 17)}

    assert read.classify_answers(inks) is None


def test_holds_a_walkout_sheet_with_two_answers():
    """두 문항만 풀고 나간 장 — lead 중앙값이 잡음 수준으로 무너진다.

    실측: 실물 65장을 2문항만 남기고 나머지를 그 장의 실제 빈 줄로 바꿨더니
    장마다 10~14문항이 답으로 승격됐다(기준선이 잡음 lead 의 40% = 3~9 로 추락).
    """
    inks = {question: glyph_noise_row(question) for question in range(1, 17)}
    inks[1] = row(c1=30.0, c2=150.0, c3=30.0, c4=30.0, c5=30.0)
    inks[2] = row(c1=30.0, c2=30.0, c3=30.0, c4=150.0, c5=30.0)

    assert read.classify_answers(inks) is None


def test_holds_at_exactly_half_marked():
    """마킹 8줄 = 절반은 아직 부족하다 — 16줄 중앙값에 잡음이 낀다.

    실측: 실물 65장을 8문항만 남겼더니 31장에서 잡음 103건이 답으로 승격됐고,
    그중 23장은 sheet_lead 42.6~70.0 이라 sheet_lead 하한으로는 못 거른다 —
    그래서 하한이 아니라 마킹 줄 수로 가른다.
    """
    inks = {question: glyph_noise_row(question) for question in range(1, 17)}
    for question in range(1, 9):
        inks[question] = row(c1=30.0, c2=30.0, c3=150.0, c4=30.0, c5=30.0)

    assert read.classify_answers(inks) is None


def test_still_reads_a_sheet_when_marks_hold_the_majority():
    """9줄이 마킹이면 중앙값은 연필 통계다 — 판정은 그대로 간다."""
    inks = {question: glyph_noise_row(question) for question in range(1, 17)}
    for question in range(1, 10):
        inks[question] = row(c1=30.0, c2=30.0, c3=150.0, c4=30.0, c5=30.0)

    readings = read.classify_answers(inks)

    assert readings is not None
    assert all(readings[question] == (3,) for question in range(1, 10))
    assert all(readings[question] == () for question in range(10, 17))


def varied_sheet(lead=90, count=16):
    """답이 흩어진 장 — 한 선택지만 계속 찍으면 그 열의 중앙값까지 오염된다."""
    answers = (1, 4, 2, 5, 3, 1, 4, 2, 5, 3, 1, 4, 2, 5, 3, 1)
    return {
        question: {
            choice: (30.0 + lead if choice == answers[(question - 1) % 16] else 30.0)
            for choice in range(1, 6)
        }
        for question in range(1, count + 1)
    }


def test_reports_all_three_marks_when_a_row_has_three():
    """세 칸을 칠하면 셋 다 넘긴다 — 줄 기준선만 쓰면 하나만 나간다.

    "나머지 넷"에 마킹이 둘 들어와 기준선이 마킹 높이의 절반까지 오르기 때문이다.
    장 중앙 lead 가 100 미만이면 발생하고, 코퍼스의 25%(16/65장)가 그 아래다.
    """
    inks = varied_sheet(lead=90)
    inks[5] = row(c1=120.0, c2=120.0, c3=120.0, c4=30.0, c5=30.0)

    assert read.classify_answers(inks)[5] == (1, 2, 3)


def test_reports_four_marks_instead_of_blank():
    """넉 칸을 칠하면 넷 다 넘긴다 — 줄 기준선만 쓰면 **빈칸**이 나간다.

    넉 칸이면 나머지 넷의 중앙값이 마킹 그 자체가 되어 높이가 전부 0 이 된다.
    학생이 넷을 칠했는데 "무응답"으로 채점되는, 아무 신호 없는 오답이다.
    """
    inks = varied_sheet(lead=120)
    inks[5] = row(c1=150.0, c2=150.0, c3=150.0, c4=150.0, c5=30.0)

    assert read.classify_answers(inks)[5] == (1, 2, 3, 4)


def test_reports_all_five_when_everything_is_filled():
    """다섯 칸 전부 칠해도 빈칸이 아니다 — 사람에게 넘어가야 할 장이다."""
    inks = varied_sheet(lead=120)
    inks[5] = row(c1=150.0, c2=150.0, c3=150.0, c4=150.0, c5=150.0)

    assert read.classify_answers(inks)[5] == (1, 2, 3, 4, 5)


def test_glyph_noise_stays_blank_on_a_faint_sheet():
    """흐린 장에서도 인쇄 글리프는 답이 아니다 — 상대 문턱만으로는 새어 나간다.

    실물 세 장의 안 칠한 줄에서 5번 글리프가 답으로 승격됐다. 쌍선형 실측에서
    진짜 빈 줄의 lead 는 최대 11.7 이고, 절대 상한 20 이 그 위를 자른다.
    """
    inks = varied_sheet(lead=46)
    inks[5] = row(c1=31.5, c2=38.0, c3=35.0, c4=31.5, c5=41.0)

    assert read.classify_answers(inks)[5] == ()


def test_flags_an_x_cancel_in_a_light_glyph_cell():
    """글리프가 가벼운 칸(1·4번) 위의 X 취소도 잡는다.

    줄 기준선은 무거운 칸(5번 47.0)과 가벼운 칸(1번 31.6)을 한 값으로 뭉개
    가벼운 칸 마킹의 높이를 약 15 깎는다 — 제일 흐린 장에서 진짜 X 가 복수
    문턱 밑으로 숨었다. 열 기준선이 그 차이를 되살린다.
    """
    inks = varied_sheet(lead=46)
    inks[5] = row(c1=31.5, c2=78.0, c3=35.0, c4=62.0, c5=49.0)

    assert read.classify_answers(inks)[5] == (2, 4)


def test_holds_a_sheet_when_a_row_reads_bare_paper():
    """줄 기준선이 맨 종이면 격자가 지면을 벗어난 것이다 — 장째 보류.

    실물 1040줄의 기준선은 전부 24.5 이상이었다(칸마다 인쇄 글리프가 있으니
    잉크가 반드시 남는다). 맨 종이는 0~5 다. 접힘·뒤틀림으로 표본이 격자 밖으로
    나가면 여기서 걸린다 — 실측: 국소 40px 뒤틀림에서 65장 전원 보류.
    """
    inks = varied_sheet(lead=90)
    inks[7] = row(c1=2.0, c2=3.0, c3=2.5, c4=1.0, c5=3.5)

    assert read.classify_answers(inks) is None


def test_holds_a_sheet_with_a_half_strength_mark():
    """빈칸도 마킹도 아닌 줄이 하나라도 있으면 장째 보류다.

    실측(65장·1040줄): 빈칸의 lead 비는 최대 0.094, 마킹은 최소 0.342 로 그
    사이가 통째로 비어 있다. 접힘·잘림으로 희석된 마킹이 정확히 거기 떨어지는데,
    예전 규칙은 그걸 조용히 "무응답"으로 채점했다 — 학생이 답한 문항이 빈칸이 된다.
    """
    inks = varied_sheet(lead=100)
    inks[6] = row(c1=30.0, c2=30.0, c3=50.0, c4=30.0, c5=30.0)

    assert read.classify_answers(inks) is None

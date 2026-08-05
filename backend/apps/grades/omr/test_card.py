"""판형 계약 — 카드 위 셀이 어디에 몇 개 있나.

여기 있는 값은 **빈 카드 실물에서 잰 것**이다(2026-08-04, `test-omr-blank.pdf`
200dpi 렌더). 판형이 바뀌면 이 표만 갈아 끼운다 — 읽는 코드는 그대로다.

셀 개수 328(성명 188 + 전화 40 + 답란 100)은 실측 검출 수와 정확히 일치했다.
그 수가 여기서 깨지면 판형 값이 어긋난 것이므로 테스트가 먼저 잡는다.
"""
from . import card


def test_answer_grid_is_twenty_questions_by_five_choices():
    cells = card.answer_cells()

    assert len(cells) == 100
    assert {question for (question, _), _ in cells} == set(range(1, 21))
    assert {choice for (_, choice), _ in cells} == set(range(1, 6))


def test_answer_lattice_keeps_its_calibrated_position():
    """실물로 맞춘 자리를 고정한다 — 조용히 밀리면 셀 중심이 버블 링에 걸친다.

    빈 카드 PDF 값을 그대로 쓰면 링 위에 얹혔고, 65장 평균판으로 맞춘 뒤에야
    중심에 왔다. 그 보정이 사라지는 것을 여기서 잡는다.
    """
    by_key = dict(card.answer_cells())

    first_u, first_v = by_key[(1, 1)]
    last_u, last_v = by_key[(20, 5)]
    assert round(first_u, 5) == 0.52278
    assert round(first_v, 5) == 0.10154
    assert round(last_u, 5) == 0.59653
    assert round(last_v, 5) == 0.92243


def test_every_answer_cell_sits_inside_the_marker_quad():
    """정규좌표는 마커 사각형이다 — 셀이 그 밖으로 나가면 판형 값이 틀린 것이다."""
    for _, (u, v) in card.answer_cells():
        assert 0.0 < u < 1.0
        assert 0.0 < v < 1.0


def test_sampling_radius_stays_inside_the_printed_stadium():
    """표본 반경 계약 — 65% 표본 발자국이 실측 테두리 안 여백을 넘으면 안 된다.

    실물 답란 버블은 폭 18.3 x 높이 33.2px(200dpi)의 스타디움이고 테두리 안
    여백은 반폭 7.9 x 반높이 15.4px 다. 65% 표본이 이 안에 있어야 빈칸이 링을
    물어 칠한 것처럼 읽히지 않는다 — 옛 반경(14.5)에서는 표본이 오프셋 0 에서
    이미 링 위에 얹혀, 답 안 한 문항 3건이 5번으로 읽혔다(65장 실측).
    """
    radius_u, radius_v = card.ANSWER_BUBBLE_RADIUS

    assert 0.65 * radius_u * 2223.5 < 7.9
    assert 0.65 * radius_v * 1493.5 < 15.4

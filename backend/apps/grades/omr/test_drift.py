"""회차 드리프트 측정 계약 — 배치가 판형에서 얼마나 밀렸나.

실물 6배치(2026-03·04·06)에서 전부 ±3px 안에 들어왔다(중앙 0.11~2.89) —
지금 `card.py` 좌표가 세 회차에 다 맞는다는 뜻이고, 그게 이 측정기의 기준선이다.

**잉크 최대화로 재면 안 된다**(첫 판의 실패): 버블은 속이 빈 스타디움이라
안쪽에 인쇄된 글자가 있어, 중심 주변 잉크를 세면 링이 아니라 그 글자를 잰다.
그때는 좌표를 맞춰 둔 회차까지 -7.5px 로 나왔다.
"""
import cv2
import numpy as np

from . import card, drift, normalize
from .test_sheet import GLYPH_GREY, MARK_GREY, blank_card

FRAME = normalize.CardFrame(
    np.array(
        [[1525.0, 120.0], [1525.0, 2225.0], [115.0, 2225.0], [115.0, 120.0]],
        dtype=np.float64,
    )
)


def card_shifted_by(dv_plate):
    """답란 전체를 `dv_plate` px(평균판 기준) 아래로 옮겨 그린 합성 카드."""
    image = blank_card()
    shift = dv_plate / 1493.5
    for (question, choice), (u, v) in card.answer_cells():
        x, y = FRAME.to_source(u, v + shift)
        # 링만 그린다 — 인쇄된 버블은 속이 비어 있다(측정 대상이 그 테두리다).
        cv2.ellipse(image, (int(round(x)), int(round(y))), (11, 16), 0, 0, 360, GLYPH_GREY, 2)
    return image


def test_a_batch_on_the_layout_reports_no_drift():
    result = drift.measure([card_shifted_by(0.0) for _ in range(12)])

    assert result is not None
    assert abs(result["dv"]) < drift.WARN_PX
    assert result["warn"] is False


def test_a_shifted_batch_is_measured_and_flagged():
    """회차 카드가 밀리면 판독은 조용히 다른 답을 낸다 — 그 전에 잡는다."""
    result = drift.measure([card_shifted_by(6.0) for _ in range(12)])

    assert result["warn"] is True
    assert 4.0 < result["dv"] < 8.0, result


def test_it_refuses_to_measure_a_thin_batch():
    """장이 적으면 연필이 평균에 안 묻힌다 — 못 재면 지어내지 않는다."""
    assert drift.measure([card_shifted_by(0.0) for _ in range(3)]) is None


def test_pages_without_a_card_do_not_count():
    width, height = 1651, 2335
    blank = [np.full((height, width), 255, np.uint8) for _ in range(20)]

    assert drift.measure(blank) is None


def test_the_accumulator_matches_measuring_them_all_at_once():
    """누산기는 메모리를 아끼는 것이지 값을 바꾸는 것이 아니다."""
    images = [card_shifted_by(4.0) for _ in range(12)]
    accumulator = drift.Accumulator()
    for image in images:
        accumulator.add(image)

    assert accumulator.result() == drift.measure(images)


def test_mark_grey_is_unused_here():
    """마킹은 평균에서 묻힌다 — 이 측정은 인쇄만 본다(픽스처가 링만 그리는 이유)."""
    assert MARK_GREY < GLYPH_GREY

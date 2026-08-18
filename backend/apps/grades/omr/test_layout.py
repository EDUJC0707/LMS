"""우리가 찍는 카드의 판형 — 설계값과 그려진 지면이 어긋나지 않는지 (설계 문서 §6).

검증 축:
- 판형 막대: 2진 인코딩·패리티·앵커. **막대 하나가 사라져도 조용히 다른 판형이
  되면 안 된다** — 수능의 개수 세기 방식이 가진 결함이 이것이다
- 신원란·답란 1열은 **옛 카드와 같은 자리**여야 한다(대표 "지금대로")
- 생성한 PDF 를 다시 재서 설계값과 맞는지 — 이 왕복이 없으면 생성기가 조용히
  틀어져도 아무도 모른다
"""
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from . import card, generate, layout

sx, sy = float(layout.SPAN_X_MM), float(layout.SPAN_Y_MM)


class TestBars:
    def test_every_layout_round_trips(self):
        for card_layout in layout.LAYOUTS:
            assert layout.decode_bars(card_layout.bars()) == card_layout.layout_id

    def test_a_lost_bar_is_refused_not_misread(self):
        """수능식 개수 세기의 결함 — 막대 하나가 빠지면 탐구(5)가 한국사(4)가 된다.

        자리를 고정하고 패리티를 두면 그 장은 **읽히지 않는다.** 조용히 틀리느니
        보류가 낫다.
        """
        for card_layout in layout.LAYOUTS:
            slots = card_layout.bars()
            for slot in layout.DATA_SLOTS:
                if not slots[slot]:
                    continue
                broken = list(slots)
                broken[slot] = False
                assert layout.decode_bars(broken) is None

    def test_an_extra_bar_is_refused(self):
        for card_layout in layout.LAYOUTS:
            slots = card_layout.bars()
            for slot in layout.DATA_SLOTS:
                if slots[slot]:
                    continue
                broken = list(slots)
                broken[slot] = True
                assert layout.decode_bars(broken) is None

    def test_a_lost_anchor_is_refused(self):
        """앵커가 없으면 슬롯 자리를 역산할 수 없다 — 셀 수는 있어도 읽으면 안 된다."""
        for anchor in layout.ANCHOR_SLOTS:
            slots = layout.encode_bars(3)
            slots[anchor] = False
            assert layout.decode_bars(slots) is None

    def test_ids_are_distinct(self):
        codes = {tuple(c.bars()) for c in layout.LAYOUTS}
        assert len(codes) == len(layout.LAYOUTS)


class TestGrid:
    def test_the_20_question_card_keeps_the_328_bubble_checksum(self):
        """card.py 의 검산값이다 — 성명 188 + 전화 40 + 답란 100."""
        cells = layout.BY_NAME["답안20"].answer_cells()
        answers = sum(len(row) for row in cells.values())
        assert len(layout.name_cells()) == 188
        assert len(layout.phone_cells()) == 40
        assert answers == 100
        assert len(layout.name_cells()) + len(layout.phone_cells()) + answers == 328

    def test_column_one_sits_exactly_on_the_old_card(self):
        """1열은 물려받는다 — 어긋나면 옛 스캔과 새 스캔이 다른 격자가 된다."""
        cells = layout.BY_NAME["답안40"].answer_cells()
        rows = card._even_span(card.ANSWER_ROW_Y, card.ANSWER_QUESTIONS)
        for question in range(1, 21):
            for index, (u, v) in enumerate(cells[question]):
                assert abs(u - card._u_avg(card.ANSWER_CHOICE_X[index] - 56.5)) * sx < 0.01
                assert abs(v - card._v_avg(rows[question - 1] - 88.5)) * sy < 0.01

    @pytest.mark.parametrize(
        "name,questions,columns",
        [("답안20", 20, 1), ("답안25", 25, 2), ("답안30", 30, 2),
         ("답안35", 35, 2), ("답안40", 40, 2)],
    )
    def test_sizes_and_columns(self, name, questions, columns):
        card_layout = layout.BY_NAME[name]
        assert card_layout.questions == questions
        assert card_layout.columns == columns
        assert len(card_layout.answer_cells()) == questions

    def test_every_cell_stays_inside_the_marker_frame(self):
        """정규좌표가 0..1 을 벗어나면 마커 밖이라 호모그래피가 못 편다."""
        for card_layout in layout.LAYOUTS:
            cells = [uv for row in card_layout.answer_cells().values() for uv in row]
            cells += list(layout.name_cells().values())
            cells += list(layout.phone_cells().values())
            for u, v in cells:
                assert 0.0 < u < 1.0, (card_layout.name, u)
                assert 0.0 < v < 1.0, (card_layout.name, v)

    def test_the_sample_window_stays_inside_the_printed_ring(self):
        """리더는 반경의 65% 를 표본한다. 선 굵기를 더해도 링을 안 물어야 한다."""
        inner = float(layout.BUBBLE_W_MM) / 2 - float(layout.STROKE_MM)
        assert float(layout.BUBBLE_W_MM) / 2 * 0.65 < inner


class TestRender:
    def test_every_layout_renders(self):
        for card_layout in layout.LAYOUTS:
            pdf = generate.render(card_layout)
            assert pdf.startswith(b"%PDF")

    @pytest.mark.skipif(not shutil.which("pdftoppm"), reason="pdftoppm 없음")
    def test_the_drawn_page_measures_back_to_the_design(self):
        """왕복 검증 — 그린 것을 다시 재서 설계값과 맞나(설계 문서 §6).

        이 테스트가 없으면 생성기가 조용히 틀어져도 아무도 모른다. 실제로
        여기서 두 가지가 잡혔다: 마커 기준이 아니라 지면 모서리 기준으로 적은
        좌표(11mm 오차)와, 너무 얇아 링이 조각나던 선 굵기.
        """
        cv2 = pytest.importorskip("cv2")
        import numpy as np

        card_layout = layout.BY_NAME["답안40"]
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "card.pdf"
            pdf.write_bytes(generate.render(card_layout))
            subprocess.run(
                ["pdftoppm", "-png", "-r", "200", str(pdf), str(Path(tmp) / "page")],
                check=True, capture_output=True,
            )
            page = next(Path(tmp).glob("page*.png"))
            image = cv2.imread(str(page), cv2.IMREAD_GRAYSCALE)

        ink = (image < 128).astype(np.uint8)
        count, _, stats, centres = cv2.connectedComponentsWithStats(ink, 8)

        solid = [
            (centres[i][0], centres[i][1])
            for i in range(1, count)
            if stats[i][4] > 0.85 * stats[i][2] * stats[i][3]
            and 6 < stats[i][2] < 25 and 10 < stats[i][3] < 30
        ]
        edge = [m for m in solid if m[0] < image.shape[1] * 0.1 or m[0] > image.shape[1] * 0.9]
        mark_x = (min(m[0] for m in edge), max(m[0] for m in edge))
        mark_y = (min(m[1] for m in edge), max(m[1] for m in edge))

        # 마커가 설계 자리에 있나 (200dpi)
        for got, want_mm in ((mark_x[0], layout.MARK_X_MM[0]), (mark_x[1], layout.MARK_X_MM[1])):
            assert abs(got - float(want_mm) / 25.4 * 200) / 200 * 25.4 < 0.2

        rings = [
            (centres[i][0], centres[i][1])
            for i in range(1, count)
            if 14 < stats[i][2] < 26 and 26 < stats[i][3] < 42
            and stats[i][4] < 0.85 * stats[i][2] * stats[i][3]
        ]
        # 답란 200 + 전화 40. 성명은 정원이라 이 필터에 안 걸린다.
        assert len(rings) == 240

        found = np.array([
            [(x - mark_x[0]) / (mark_x[1] - mark_x[0]),
             (y - mark_y[0]) / (mark_y[1] - mark_y[0])]
            for x, y in rings
        ])
        want = [uv for row in card_layout.answer_cells().values() for uv in row]
        want += list(layout.phone_cells().values())
        for u, v in want:
            distance = np.hypot((found[:, 0] - u) * sx, (found[:, 1] - v) * sy).min()
            assert distance < 0.35, (u, v, distance)

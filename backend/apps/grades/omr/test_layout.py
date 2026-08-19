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
    def test_the_identity_block_keeps_its_228_bubble_checksum(self):
        """card.py 의 검산값 중 신원란 몫 — 성명 188 + 전화 40."""
        assert len(layout.name_cells()) == 188
        assert len(layout.phone_cells()) == 40

    def test_the_survey_score_is_one_column_tens_over_ones(self):
        """원본 조사 카드가 그렇다 — 두 열로 갈라 놓으면 지면이 달라진다."""
        cells = layout.BY_NAME["성적조사"].survey_cells()
        assert len(cells) == 15
        us = {round(u, 6) for u, _ in cells.values()}
        assert len(us) == 1, "점수칸은 한 열이어야 한다"
        tens = [v for (place, _), (_, v) in cells.items() if place == "십"]
        ones = [v for (place, _), (_, v) in cells.items() if place == "일"]
        assert max(tens) < min(ones), "십의 자리가 위에 온다"

    def test_the_answer_grid_no_longer_matches_the_old_card(self):
        """옛 카드와의 일치는 **의도적으로 깼다**(대표 2026-08-19).

        25문항이 최대라 지면 오른쪽이 남았고, 옛 카드의 5.21mm 간격은 촘촘했다.
        6.4mm 로 벌리면서 답 버블이 옛 좌표를 떠났다 — 그래서 **새 카드는
        `card.py` 로 읽으면 안 된다.** 무엇이 가르는지는 가장자리 막대다.

        이 테스트는 그 사실을 못 박아 둔다: 둘이 우연히 다시 같아지면
        (누가 간격을 되돌리면) 여기서 걸려 리더 배선을 다시 보게 된다.
        """
        cells = layout.BY_NAME["답안25"].answer_cells()
        drift = abs(cells[1][0][0] - card._u_avg(card.ANSWER_CHOICE_X[0] - 56.5)) * sx
        assert drift > 1.0, (
            "답 버블이 옛 카드 좌표로 돌아왔다 — 리더 배선을 확인할 것"
        )

    def test_the_choice_pitch_is_the_wider_one(self):
        assert float(layout.CHOICE_PITCH_MM) > 6.0

    @pytest.mark.parametrize(
        "name,questions,columns",
        [("답안20", 20, 1), ("답안25", 25, 2)],
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

        card_layout = layout.BY_NAME["답안25"]
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "card.pdf"
            pdf.write_bytes(generate.render(card_layout))
            subprocess.run(
                ["pdftoppm", "-png", "-r", "200", str(pdf), str(Path(tmp) / "page")],
                check=True, capture_output=True,
            )
            page = next(Path(tmp).glob("page*.png"))
            image = cv2.imread(str(page), cv2.IMREAD_GRAYSCALE)

        # 카드가 2도 인쇄라 문턱을 색에 맞춘다: 분홍 링은 회색값 약 106,
        # 연초록 바탕은 217 이다. 128 로 자르면 링이 조각난다.
        ink = (image < 170).astype(np.uint8)
        count, _, stats, centres = cv2.connectedComponentsWithStats(ink, 8)

        solid = [
            (centres[i][0], centres[i][1])
            for i in range(1, count)
            # 위 마커는 아래보다 키가 크다(4.95 대 2.79mm) — 둘 다 들어오게 잡는다.
            if stats[i][4] > 0.85 * stats[i][2] * stats[i][3]
            and 12 < stats[i][2] < 30 and 15 < stats[i][3] < 48
        ]
        edge = [m for m in solid if m[0] < image.shape[1] * 0.1 or m[0] > image.shape[1] * 0.9]
        mark_x = (min(m[0] for m in edge), max(m[0] for m in edge))
        mark_y = (min(m[1] for m in edge), max(m[1] for m in edge))

        # 마커가 설계 자리에 있나 (200dpi)
        for got, want_mm in ((mark_x[0], layout.MARK_X_MM[0]), (mark_x[1], layout.MARK_X_MM[1])):
            assert abs(got - float(want_mm) / 25.4 * 200) / 200 * 25.4 < 0.2

        rings = np.array([
            [(centres[i][0] - mark_x[0]) / (mark_x[1] - mark_x[0]),
             (centres[i][1] - mark_y[0]) / (mark_y[1] - mark_y[0])]
            for i in range(1, count)
            if 14 < stats[i][2] < 26 and 26 < stats[i][3] < 42
            and stats[i][4] < 0.85 * stats[i][2] * stats[i][3]
        ])

        want = [uv for row in card_layout.answer_cells().values() for uv in row]
        want += list(card_layout.extra_cells().values())
        want += list(layout.phone_cells().values())

        # 링을 **설계 칸 기준으로** 센다. 지면 전체를 세면 로고 속 빈 공간이나
        # 굵은 글자 획까지 링으로 잡힌다 — 그건 결함이 아니라 검출기의 한계다.
        matched = 0
        for u, v in want:
            distance = np.hypot((rings[:, 0] - u) * sx, (rings[:, 1] - v) * sy)
            assert distance.min() < 0.35, (u, v, distance.min())
            matched += int((distance < 0.35).sum())
        assert matched == len(want), "칸 하나에 링이 둘이면 격자가 겹친 것이다"


class TestBarReading:
    """스캔 원본에서 판형을 읽는다 — 어긋난 스캔에서도, 그리고 **틀리게는 안 읽는다**.

    인코딩이 튼튼한 것과 실제로 읽히는 것은 다른 얘기다. 여기서 재는 것은 후자다.
    """

    @staticmethod
    def page(card, dpi=200):
        import cv2
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "c.pdf"
            pdf.write_bytes(generate.render(card))
            subprocess.run(
                ["pdftoppm", "-png", "-r", str(dpi), str(pdf), str(Path(tmp) / "x")],
                check=True, capture_output=True,
            )
            return cv2.imread(str(next(Path(tmp).glob("x*.png"))), 0)

    @pytest.mark.skipif(not shutil.which("pdftoppm"), reason="pdftoppm 없음")
    def test_every_layout_reads_back_off_a_clean_scan(self):
        pytest.importorskip("cv2")
        from . import bars
        for sheet in layout.LAYOUTS:
            assert bars.read_layout(self.page(sheet)) == sheet.layout_id

    @pytest.mark.skipif(not shutil.which("pdftoppm"), reason="pdftoppm 없음")
    def test_it_survives_a_crooked_scanner(self):
        """앵커가 좌표계를 만들므로 배율·평행이동·기울기가 흡수된다."""
        cv2 = pytest.importorskip("cv2")
        import numpy as np

        from . import bars

        card = layout.BY_NAME["답안25"]
        image = self.page(card)
        height, width = image.shape

        def turn(degrees):
            matrix = cv2.getRotationMatrix2D((width / 2, height / 2), degrees, 1.0)
            return cv2.warpAffine(image, matrix, (width, height), borderValue=255)

        cases = {
            "회전 -2도": turn(-2.0),
            "회전 +4도": turn(4.0),
            "축소 92%": cv2.resize(image, None, fx=0.92, fy=0.92),
            "확대 108%": cv2.resize(image, None, fx=1.08, fy=1.08),
            "평행이동": cv2.warpAffine(
                image, np.float32([[1, 0, 30], [0, 1, 18]]), (width, height),
                borderValue=255,
            ),
            "저해상도 100dpi": self.page(card, 100),
        }
        for name, degraded in cases.items():
            assert bars.read_layout(degraded) == card.layout_id, name

    @pytest.mark.skipif(not shutil.which("pdftoppm"), reason="pdftoppm 없음")
    def test_one_ruined_edge_is_carried_by_the_other(self):
        """좌우 이중으로 둔 이유다 — 스캔에서 가장자리가 날아가는 일이 있다."""
        pytest.importorskip("cv2")
        from . import bars

        card = layout.BY_NAME["답안25"]
        image = self.page(card)
        width = image.shape[1]
        for cut in (slice(0, int(width * 0.08)), slice(int(width * 0.92), width)):
            damaged = image.copy()
            damaged[:, cut] = 255
            assert bars.read_layout(damaged) == card.layout_id

    @pytest.mark.skipif(not shutil.which("pdftoppm"), reason="pdftoppm 없음")
    def test_disagreeing_edges_are_refused(self):
        """한쪽이 오염되면 어느 쪽을 믿을지 알 수 없다 — 조용히 고르지 않는다."""
        pytest.importorskip("cv2")
        from . import bars

        sheet = self.page(layout.BY_NAME["답안25"])
        other = self.page(layout.BY_NAME["성적조사"])
        width = sheet.shape[1]
        # **왼쪽 가장자리만** 갈아 끼운다. 오른쪽을 덮으면 막대가 깨져 읽기
        # 실패로 떨어지고, 그건 "한쪽이 망가지면 반대쪽으로 읽는다"는 다른
        # 경로다. 여기서 재려는 건 **둘 다 읽히는데 서로 다른** 경우다.
        spliced = sheet.copy()
        spliced[:, : int(width * 0.05)] = other[:, : int(width * 0.05)]
        assert bars.read_layout(spliced) is None

    def test_a_sheet_without_bars_reads_as_unknown(self):
        """옛 튜터시스템 카드다. 판형을 지어내지 않고 `exams.kind` 로 넘긴다."""
        pytest.importorskip("cv2")
        import numpy as np

        from . import bars
        assert bars.read_layout(np.full((1654, 2339), 255, dtype=np.uint8)) is None


class TestTextFits:
    """안내 문구가 박스를 넘지 않는지 — **자동 축소를 걷어낸 대가로** 필요한 검사.

    예전에는 넘치는 줄만 글자를 줄였다. 그래서 안 터지는 대신 한 문단에서
    크기가 5.7 / 7.2 / 4.7pt 로 튀었다. 이제는 고정 크기라 넘치면 정말로
    삐져나오므로, 여기서 잡아 문구를 나누거나 박스를 넓히게 만든다.
    """

    @staticmethod
    def worst(lines, box, indents_mm, size_of):
        generate._font()
        span = float(layout.SPAN_X_MM)
        u0, _, u1, _ = box
        return max(
            generate.overflow(
                line, size_of(indent),
                u1 - u0 - (indents_mm[indent] + generate.TEXT_RIGHT_MM) / span,
            )
            for line, indent, *_ in lines
            if line
        )

    def test_the_rules_box_holds_its_text(self):
        over = self.worst(
            generate.RULES + generate.RULES_TAIL, generate.BOX_RULES,
            generate.RULES_INDENT_MM,
            lambda i: generate.RULES_NOTE_PT if i == 2 else generate.RULES_PT,
        )
        assert over <= 0, f"지켜야 할 사항 문구가 {over:.2f}mm 넘친다"

    def test_the_phone_note_holds_its_text(self):
        over = self.worst(
            generate.PHONE_HOW, generate.BOX_PHONE_HOW,
            generate.PHONE_INDENT_MM, lambda _i: generate.PHONE_PT,
        )
        assert over <= 0, f"전화번호 마킹방법 문구가 {over:.2f}mm 넘친다"

    def test_the_inline_bubble_line_holds(self):
        """`2. 표기란에는 ● 와 같이 바르게` 는 글자+버블+글자 폭을 다 더해야 한다."""
        generate._font()
        u0, _, u1, _ = generate.BOX_RULES
        head = next(line for line, *_ in generate.RULES if line.startswith("2."))
        width_mm = (
            generate._width(head, generate.RULES_PT) / generate.MM_UNIT
            + generate._width(generate.RULE_MARK_TAIL, generate.RULES_PT) / generate.MM_UNIT
            + float(layout.BUBBLE_W_MM) + 3.2
        )
        room = (u1 - u0) * float(layout.SPAN_X_MM) - (
            generate.RULES_INDENT_MM[0] + generate.TEXT_RIGHT_MM
        )
        assert width_mm <= room, f"2번 줄이 {width_mm - room:.2f}mm 넘친다"


    def test_the_rules_box_holds_its_text_vertically(self):
        """가로만 재면 마지막 줄이 박스 아래로 새는 것을 못 잡는다 — 실제로 샜다."""
        span = float(layout.SPAN_Y_MM)
        top, bottom = generate.BOX_RULES[1], generate.BOX_RULES[3]
        used = generate.RULES_BODY_V * span + sum(a for *_, a in generate.RULES)
        used += generate.WRONG_ADVANCE_MM + sum(a for *_, a in generate.RULES_TAIL)
        used += 2.1  # 마지막 줄 글자 높이
        room = (bottom - top) * span
        assert used <= room, f"세로로 {used - room:.2f}mm 넘친다"


class TestJamoMatchesTheReader:
    """지면에 찍는 자모와 리더가 읽는 자모는 **같은 목록이어야 한다**.

    두 벌로 두었을 때 실제로 갈렸다: 지면은 유니코드 순서, 리더는 카드 순서
    (홑모음 10 → 이중모음 4 → 복합모음 5)라 2행을 칠하면 `ㅐ` 가 `ㅑ` 로
    읽혔고, 유니코드 19칸에는 `ㅣ` 가 안 들어가 **이·기·니 가 든 이름은
    마킹할 칸조차 없었다.**
    """

    def test_the_printed_vowels_are_the_readers_vowels(self):
        from . import decode
        assert "".join(layout.VOWELS) == decode.CARD_VOWELS

    def test_the_printed_consonants_are_the_readers_consonants(self):
        from . import decode
        assert "".join(layout.CONSONANTS) == decode.CARD_CONSONANTS

    def test_every_vowel_a_name_can_need_is_on_the_card(self):
        """`ㅣ` 가 빠져 있었다 — 흔한 이름이 통째로 마킹 불가였다."""
        for vowel in "ㅏㅑㅓㅕㅗㅛㅜㅠㅡㅣ":
            assert vowel in layout.VOWELS, vowel

    def test_the_grid_has_a_row_for_every_letter(self):
        """행 수가 자모 수보다 적으면 뒤쪽 자모가 지면에서 잘린다."""
        assert len(layout.VOWELS) == layout.NAME_ROWS
        assert len(layout.CONSONANTS) == layout.NAME_CONSONANT_ROWS

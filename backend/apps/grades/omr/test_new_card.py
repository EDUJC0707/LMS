"""우리 카드가 **판독기를 실제로 통과하는가** — 렌더 → 마킹 → 열화 → 판독.

여기 오기까지 새 카드 검증은 전부 "렌더된 PDF 를 자로 재는 것"이었다. 링이
설계 좌표에 있는지는 봤지만 그 링을 칠했을 때 리더가 읽는지는 아무도 안 봤고,
그 사이에 판독 경로는 옛 카드 좌표만 쓰고 있었다.

## 무엇을 재는가

세 가지다. **읽히는가**(깨끗한 장), **어긋나도 읽히는가**(스캐너 열화),
그리고 **못 읽을 때 틀리게 읽지 않는가**(지저분한 마킹). 셋째가 제일 중요하다 —
빈칸이나 보류는 조교가 보면 되지만 **틀린 답은 그대로 성적표로 나간다.**
"""
import shutil

import pytest

from . import grid, layout

pytestmark = pytest.mark.skipif(
    not shutil.which("pdftoppm"), reason="pdftoppm 없음"
)

#: 20문항 전부에 답이 있는 회차. 선택지를 돌려 가며 써서 특정 열에 쏠리지 않게 한다.
ANSWERS_20 = {q: (q % 5) + 1 for q in range(1, 21)}
ANSWERS_25 = {q: (q % 5) + 1 for q in range(1, 26)}


def read(image, count, sheet_grid):
    from . import sheet as sheet_module
    return sheet_module.read_sheet(image, count, grid=sheet_grid)


class TestItReadsBackWhatWasMarked:
    def test_both_answer_cards_read_back_completely(self):
        """답·성명·전화·약점 체크·판형이 한 번에 다 나와야 한다."""
        pytest.importorskip("cv2")
        from . import synth

        for name, count, answers in (("답안20", 20, ANSWERS_20), ("답안25", 25, ANSWERS_25)):
            card = layout.BY_NAME[name]
            sheet_grid = grid.BY_LAYOUT[card.layout_id]
            weak = {3, 7, count - 1}
            image = synth.sheet(
                card, sheet_grid, answers, name="김민준", phone="0501", extra=weak
            )
            reading = read(image, count, sheet_grid)

            assert reading.held is None, name
            assert reading.answers == {q: (choice,) for q, choice in answers.items()}, name
            assert set(reading.extra) == weak, name
            assert reading.name == "김민준"
            assert reading.phone == "0501"
            assert reading.layout_id == card.layout_id

    def test_a_name_the_card_cannot_spell_reads_back_folded(self):
        """`꽃님` 은 카드에 `곷님` 으로 들어온다 — 학생이 그렇게 칠할 수밖에 없다.

        대조가 `fold_to_card` 로 양쪽을 낮춰 비교하는 이유가 이것이다.
        """
        pytest.importorskip("cv2")
        from . import decode, synth

        card = layout.BY_NAME["답안20"]
        sheet_grid = grid.BY_LAYOUT[1]
        image = synth.sheet(card, sheet_grid, ANSWERS_20, name="꽃님", phone="7788")
        reading = read(image, 20, sheet_grid)

        assert reading.name == decode.fold_to_card("꽃님")
        assert reading.phone == "7788"


class TestItSurvivesTheScanner:
    """실측 열화 범위 — 기울기 median -0.24° · 최대 -3.55°, 스캔은 JPEG 로 온다."""

    CASES = {
        "기울기 -2도": {"angle": -2.0},
        "기울기 +3.5도": {"angle": 3.5},
        "흐림 + JPEG 60": {"blur": 1, "jpeg": 60},
        "밝게 + 대비 낮춤": {"brightness": 50, "contrast": 0.8},
        "잡음": {"noise": 40},
        "다 같이": {"angle": -1.5, "blur": 1, "jpeg": 70, "brightness": 25, "noise": 20},
    }

    def test_answers_hold_through_each_degradation(self):
        pytest.importorskip("cv2")
        from . import synth

        card = layout.BY_NAME["답안25"]
        sheet_grid = grid.BY_LAYOUT[2]
        clean = synth.sheet(
            card, sheet_grid, ANSWERS_25, name="김민준", phone="0501", extra={3, 7, 19}
        )
        for label, how in self.CASES.items():
            reading = read(synth.degrade(clean, **how), 25, sheet_grid)
            assert reading.held is None, label
            assert reading.answers == {q: (c,) for q, c in ANSWERS_25.items()}, label
            assert set(reading.extra) == {3, 7, 19}, label


class TestMessyMarkingIsNeverReadWrong:
    """**틀린 답은 성적표로 나간다.** 빈칸·보류는 조교가 본다 — 그쪽으로 떨어져야 한다."""

    #: 리더가 읽어 내야 하는 방식 — 실물에서 흔하고, 뜻이 분명하다.
    READABLE = ("full", "light", "half", "spill", "check", "slash")
    #: 읽으면 안 되는 방식. `circle` 은 링만 덧그려 안이 비었고, `erased` 는 지운
    #: 자국이다. 둘 다 "이게 답이다"라고 말할 근거가 없다.
    NOT_AN_ANSWER = ("circle", "erased")

    def test_the_readable_ones_read_back(self):
        pytest.importorskip("cv2")
        from . import synth

        card = layout.BY_NAME["답안20"]
        sheet_grid = grid.BY_LAYOUT[1]
        for style in self.READABLE:
            image = synth.sheet(card, sheet_grid, ANSWERS_20, style=style)
            reading = read(image, 20, sheet_grid)
            assert reading.held is None, style
            assert reading.answers == {q: (c,) for q, c in ANSWERS_20.items()}, style

    def test_the_others_never_produce_an_answer(self):
        """빈칸이든 보류든 상관없다. **답이 나오면 안 된다.**"""
        pytest.importorskip("cv2")
        from . import synth

        card = layout.BY_NAME["답안20"]
        sheet_grid = grid.BY_LAYOUT[1]
        for style in self.NOT_AN_ANSWER:
            image = synth.sheet(card, sheet_grid, ANSWERS_20, style=style)
            reading = read(image, 20, sheet_grid)
            if reading.held is not None:
                continue
            for question, choices in reading.answers.items():
                assert not choices, f"{style} {question}번이 답으로 읽혔다: {choices}"

    def test_one_sheet_mixing_every_style_still_never_lies(self):
        """한 장 안에 여러 방식이 섞이는 것이 실물이다 — 장 눈금이 흔들린다."""
        pytest.importorskip("cv2")
        from . import synth

        card = layout.BY_NAME["답안20"]
        sheet_grid = grid.BY_LAYOUT[1]
        styles = {q: synth.STYLES[q % len(synth.STYLES)] for q in ANSWERS_20}
        reading = read(
            synth.sheet(card, sheet_grid, ANSWERS_20, styles=styles), 20, sheet_grid
        )

        assert reading.held is None
        for question, choices in reading.answers.items():
            if styles[question] in self.NOT_AN_ANSWER:
                assert not choices, f"{styles[question]} 가 답으로 읽혔다"
            else:
                assert choices == (ANSWERS_20[question],), styles[question]


class TestThePaperPicksTheGrid:
    def test_the_bars_choose_the_layout_not_the_exam(self):
        """한 배치에 20문항 카드와 25문항 카드가 섞여 들어올 수 있다."""
        pytest.importorskip("cv2")
        from . import bars, normalize, synth

        for name in ("답안20", "답안25"):
            card = layout.BY_NAME[name]
            image = synth.page(card)
            frame = normalize.locate_card(image)
            assert frame is not None, name
            assert bars.read_layout(image, frame) == card.layout_id, name

    def test_reading_a_new_card_on_the_old_grid_does_not_quietly_succeed(self):
        """옛 좌표로 새 카드를 읽으면 **틀린 답이 나오면 안 된다.**

        이 브랜치의 출발점이 정확히 이 위험이었다 — 답란을 벌리면서 답 버블이
        옛 좌표를 떠났고, 판독 경로는 여전히 옛 좌표만 쓰고 있었다.
        """
        pytest.importorskip("cv2")
        from . import synth

        card = layout.BY_NAME["답안20"]
        image = synth.sheet(card, grid.BY_LAYOUT[1], ANSWERS_20)
        reading = read(image, 20, grid.VENDOR)

        if reading.held is None:
            agreed = sum(
                reading.answers.get(q) == (choice,) for q, choice in ANSWERS_20.items()
            )
            assert agreed < len(ANSWERS_20), "옛 좌표가 새 카드를 다 맞혔다면 격자가 안 갈린 것이다"

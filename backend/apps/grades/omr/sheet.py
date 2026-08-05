"""장 하나를 읽는다 — 이미지 + 시험 문항 수 → 답, 아니면 보류 사유.

엔진의 네 조각(normalize·card·read)을 잇는 **유일한 이음매**다. 그 전까지는
호출부가 매번 손으로 조립했고, 특히 `{(문항, 선택지): 잉크}` 를
`{문항: {선택지: 잉크}}` 로 뒤집는 루프가 평가 스크립트마다 다시 쓰였다 —
같은 코드가 여러 벌이면 반드시 한쪽만 고치는 날이 온다.

## 층은 그대로다

이 모듈은 **조율만** 한다. normalize 는 여전히 이미지만 알고 카드를 모르며,
card 는 순수 데이터고, read 는 잉크만 알고 뜻을 모른다. 여기가 하는 일은
"어느 순서로 부르고, 무엇을 넘기고, 못 읽으면 뭐라고 답하나" 셋뿐이다.

## 보류 사유를 구분한다

`locate_card` 도 `classify_answers` 도 None 을 돌려줄 수 있는데, 둘은 조교가
할 일이 다르다:

- `CARD_NOT_FOUND` — 마커를 못 찾았거나 방향을 못 가렸다. **다시 스캔**해야 한다
- `MARKS_UNTRUSTED` — 카드는 찾았는데 그 장의 마킹 통계를 못 믿는다
  (연필이 과반이 아니거나, 빈칸도 마킹도 아닌 줄이 있다). **눈으로 확인**해야 한다

"답이 없다"와 뭉치면 안 된다 — 빈칸은 학생이 안 푼 것이고, 보류는 기계가
못 읽은 것이다.

## 문항 수는 시험이 정한다, 카드가 아니다

카드에는 답란이 20줄 있지만 시험이 그만큼 쓴다는 보장이 없다(실물 회차는
16문항짜리 하프였다). 안 쓴 줄을 판정에 넣으면 그 장의 중앙 lead 가 최대
11.6% 내려가고, 흐린 장에서 인쇄 글리프가 답으로 승격된다 — 실제로 그렇게
유령답 3건이 났었다. 그래서 문항 수는 **호출부가 반드시 준다.**
"""
from . import card, normalize, read

#: 마커를 못 찾았거나 방향을 못 가렸다 — 다시 스캔.
CARD_NOT_FOUND = "카드 없음"
#: 카드는 찾았으나 그 장의 마킹을 못 믿는다 — 사람이 확인.
MARKS_UNTRUSTED = "판독 불가"


class SheetReading:
    """판독 결과. `answers` 와 `held` 중 정확히 하나만 채워진다."""

    __slots__ = ("answers", "held", "frame")

    def __init__(self, answers=None, held=None, frame=None):
        self.answers = answers
        self.held = held
        self.frame = frame

    def __repr__(self):
        if self.held is not None:
            return f"SheetReading(held={self.held!r})"
        return f"SheetReading(answers={len(self.answers)}문항)"


def read_sheet(image, question_count):
    """장 하나를 읽는다. `question_count` 는 **그 시험의** 문항 수다.

    `frame` 을 함께 돌려주는 이유는 보정 화면이 같은 변환으로 셀 자리를
    다시 그려야 하기 때문이다 — 두 번 계산하면 두 값이 갈린다.
    """
    cells = answer_cells_for(question_count)
    frame = normalize.locate_card(image)
    if frame is None:
        return SheetReading(held=CARD_NOT_FOUND)
    inks = read.sample_cells(image, frame, cells, card.ANSWER_BUBBLE_RADIUS)
    readings = read.classify_answers(group_by_row(inks))
    if readings is None:
        return SheetReading(held=MARKS_UNTRUSTED, frame=frame)
    return SheetReading(answers=readings, frame=frame)


def answer_cells_for(question_count):
    """그 시험이 실제로 쓰는 문항의 셀만. 카드 범위를 넘으면 ValueError."""
    if not 1 <= question_count <= card.ANSWER_QUESTIONS:
        raise ValueError(
            f"문항 수 {question_count} 는 카드 범위(1~{card.ANSWER_QUESTIONS}) 밖이다."
        )
    return [cell for cell in card.answer_cells() if cell[0][0] <= question_count]


def group_by_row(inks):
    """`{(줄, 칸): 잉크}` → `{줄: {칸: 잉크}}` — 판정이 요구하는 모양.

    성명·전화도 (줄, 칸) 꼴의 키를 쓰므로 이 함수가 세 구역에 공통으로 선다.
    """
    rows = {}
    for (row, column), ink in inks.items():
        rows.setdefault(row, {})[column] = ink
    return rows

"""판독이 쓰는 좌표 한 벌 — 옛 카드와 새 카드가 **같은 모양으로** 내놓는다.

`sheet.py` 는 지금까지 `card.py` 를 직접 임포트했다. 그래서 새 카드를 읽을
방법이 없었다 — 좌표를 갈아 끼울 자리가 호출 서명 어디에도 없었기 때문이다.
여기서 그 자리를 만든다.

두 출처의 모양이 원래 조금씩 달랐다. `card` 는 `[(키, (u, v))]` 목록을,
`layout` 은 `{키: (u, v)}` 딕셔너리를 내놓고, 답란은 한쪽이 평평한 목록이고
다른 쪽이 문항별 리스트다. **차이를 여기서만 흡수한다** — 판독 쪽에는 한 모양만
간다.

## 무엇이 판형마다 다른가

답란뿐이다. 성명 격자는 새 카드가 옛 카드에서 그대로 물려받았고(정규좌표가
같은 값으로 떨어진다), 전화 4자리는 열 자리가 조금 다르지만 모양은 같다.
그래서 이 이음매는 좌표 묶음 하나로 충분하고, 판독 알고리즘은 판형을 모른다.

## 약점 체크

새 카드에만 있다. 옛 카드에는 그 칸이 없으므로 빈 목록이고, 판독은 "없으면 안
읽는다"로 자연히 갈린다 — 분기가 필요 없다.
"""
from . import card
from . import layout as L


class Grid:
    """한 판형의 좌표. `sheet` 가 이것만 보고 읽는다."""

    __slots__ = ("name", "layout_id", "questions", "answer", "answer_radius",
                 "names", "name_radius", "phones", "phone_radius", "extra")

    def __init__(self, name, layout_id, questions, answer, answer_radius,
                 names, name_radius, phones, phone_radius, extra=()):
        self.name = name
        self.layout_id = layout_id
        self.questions = questions
        self.answer = answer
        self.answer_radius = answer_radius
        self.names = names
        self.name_radius = name_radius
        self.phones = phones
        self.phone_radius = phone_radius
        self.extra = extra

    def __repr__(self):
        return f"Grid({self.name!r}, {self.questions}문항)"

    def answer_cells(self, question_count):
        """그 시험이 실제로 쓰는 문항의 셀만. 판형 범위를 넘으면 ValueError.

        카드에 답란이 몇 줄 있든 시험이 그만큼 쓴다는 보장이 없다(실물 회차는
        16문항짜리 하프였다). 안 쓴 줄을 판정에 넣으면 그 장의 중앙 lead 가
        내려가 인쇄 글리프가 답으로 승격된다.
        """
        if not 1 <= question_count <= self.questions:
            raise ValueError(
                f"문항 수 {question_count} 는 {self.name} 범위"
                f"(1~{self.questions}) 밖이다."
            )
        return [cell for cell in self.answer if cell[0][0] <= question_count]

    def extra_cells(self, question_count):
        """약점 체크 칸 — 그 시험이 쓰는 문항만. 없는 판형이면 빈 목록."""
        return [cell for cell in self.extra if cell[0][0] <= question_count]


def _vendor():
    """옛 튜터시스템 카드 — 실물 65장으로 검증된 좌표 그대로."""
    return Grid(
        name="튜터시스템 2012",
        layout_id=None,
        questions=card.ANSWER_QUESTIONS,
        answer=card.answer_cells(),
        answer_radius=card.ANSWER_BUBBLE_RADIUS,
        names=card.name_cells(),
        name_radius=card.NAME_BUBBLE_RADIUS,
        phones=card.phone_cells(),
        phone_radius=card.PHONE_BUBBLE_RADIUS,
    )


def _from_layout(sheet):
    """우리 카드 — `layout.py` 의 설계값이 곧 좌표다."""
    answer = [
        ((question, choice), point)
        for question, points in sheet.answer_cells().items()
        for choice, point in enumerate(points, start=1)
    ]
    # 약점 체크는 문항마다 한 칸뿐이라 열 번호를 1 로 채운다 — `group_by_row` 가
    # (줄, 칸) 꼴을 요구하고, 그래야 답란과 같은 함수로 묶인다.
    extra = [((question, 1), point) for question, point in sheet.extra_cells().items()]
    radius = (float(L.ANSWER_SAMPLE_RU), float(L.ANSWER_SAMPLE_RV))
    return Grid(
        name=sheet.name,
        layout_id=sheet.layout_id,
        questions=sheet.questions,
        answer=answer,
        answer_radius=radius,
        names=list(L.name_cells().items()),
        name_radius=tuple(float(r) for r in L.NAME_SAMPLE_R),
        phones=list(L.phone_cells().items()),
        phone_radius=radius,
        extra=sorted(extra),
    )


VENDOR = _vendor()
#: 판형 id -> 좌표. 막대가 읽히면 여기서 고르고, 안 읽히면 옛 카드다.
BY_LAYOUT = {
    sheet.layout_id: _from_layout(sheet)
    for sheet in L.LAYOUTS
    if not sheet.is_survey
}


#: 어떤 판형이든 담을 수 있는 최대 문항 수 — API 상한이 여기서 온다.
#: 옛 카드 20, 우리 25문항 카드 25. 판형별 상한은 `Grid.answer_cells` 가 본다.
MAX_QUESTIONS = max([VENDOR.questions] + [g.questions for g in BY_LAYOUT.values()])


def for_layout(layout_id):
    """판형 id -> 좌표. 모르는 id 면 None — 지어내지 않는다."""
    return BY_LAYOUT.get(layout_id)

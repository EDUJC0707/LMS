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
from . import card, decode, normalize, read

#: 마커를 못 찾았거나 방향을 못 가렸다 — 다시 스캔.
CARD_NOT_FOUND = "카드 없음"
#: 카드는 찾았으나 그 장의 마킹을 못 믿는다 — 사람이 확인.
MARKS_UNTRUSTED = "판독 불가"
#: 조사 카드인데 버블에 연필이 안 닿았다 — 손글씨만 남긴 장이다(사람이 옮겨 적는다).
CARD_UNMARKED = "마킹 없음"
#: 조사 카드인데 점수칸을 못 읽었다. 조사 카드는 점수가 전부라 답이 없는 것과 같다.
SCORE_UNREADABLE = "점수 판독 불가"

#: 조사 카드가 "칠해졌다"고 보는 최소 눈금. 실물 94장은 **두 무리로 갈렸다** —
#: 백지 쪽 10~19(34장), 칠한 쪽 58~160(60장). 그 사이 빈 구간에 둔다
#: (2026-08-11 실측, `read.field_scale` 기준).
#:
#: 이 문턱이 없으면 백지에서 눈금이 인쇄 잡음(≈13)이 되고, 판정 문턱이 그
#: 45% 로 내려가 **글리프가 마킹으로 승격된다** — 안 쓴 카드에서 점수가 나온다.
SURVEY_INK_FLOOR = 35.0


class SheetReading:
    """판독 결과. `answers` 와 `held` 중 정확히 하나만 채워진다.

    신원 셋(`name`·`phone`·`matching_key`)은 **답과 독립으로 실패할 수 있다** —
    답은 다 읽혔는데 전화칸을 안 쓴 학생이 실물에 있었다. 그때 장을 보류하지
    않는다: 답은 멀쩡하고 조교는 "누구 것인지만" 골라 주면 된다.
    """

    __slots__ = ("answers", "held", "frame", "name", "phone", "matching_key")

    def __init__(
        self, answers=None, held=None, frame=None, name=None, phone=None, matching_key=None
    ):
        self.answers = answers
        self.held = held
        self.frame = frame
        self.name = name
        self.phone = phone
        self.matching_key = matching_key

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
    rows = group_by_row(inks)
    readings = read.classify_answers(rows)
    if readings is None:
        return SheetReading(held=MARKS_UNTRUSTED, frame=frame)
    name, phone = read_identity(image, frame, read.sheet_scale(rows))
    return SheetReading(
        answers=readings,
        frame=frame,
        name=name,
        phone=phone,
        matching_key=decode.matching_key(name, phone),
    )


class SurveyReading:
    """성적 조사 카드 판독 결과. `score` 와 `held` 중 정확히 하나만 채워진다.

    답안 카드와 달리 **점수가 전부**라 점수를 못 읽으면 보류다. 신원은 답안
    카드와 같은 규칙으로 최선만 한다 — 이름만 읽히고 번호가 비어도 조교가
    누구 것인지 고를 수 있다(실물에서 번호칸은 셋 중 하나만 채워져 있었다).
    """

    __slots__ = ("score", "held", "frame", "name", "phone", "matching_key")

    def __init__(self, score=None, held=None, frame=None, name=None, phone=None, matching_key=None):
        self.score = score
        self.held = held
        self.frame = frame
        self.name = name
        self.phone = phone
        self.matching_key = matching_key

    def __repr__(self):
        if self.held is not None:
            return f"SurveyReading(held={self.held!r})"
        return f"SurveyReading(score={self.score})"


def read_survey(image):
    """성적 조사 카드 한 장 — 모의고사 자체채점 점수(PRD 3.1.1 · card 판형 주석).

    답란이 없어 눈금을 답란에서 못 빌린다. 성명칸에서 만든다 —
    `read.field_scale` 이 그 자리다.
    """
    frame = normalize.locate_card(image)
    if frame is None:
        return SurveyReading(held=CARD_NOT_FOUND)
    name_fields = group_by_row(
        read.sample_cells(image, frame, card.name_cells(), card.NAME_BUBBLE_RADIUS)
    )
    scale = read.field_scale(name_fields)
    if scale < SURVEY_INK_FLOOR:
        return SurveyReading(held=CARD_UNMARKED, frame=frame)

    score_fields = group_by_row(
        read.sample_cells(image, frame, card.survey_score_cells(), card.ANSWER_BUBBLE_RADIUS)
    )
    score = decode.decode_score(read.classify_fields(score_fields, scale))
    if score is None:
        return SurveyReading(held=SCORE_UNREADABLE, frame=frame)

    number_fields = group_by_row(
        read.sample_cells(image, frame, card.survey_number_cells(), card.PHONE_BUBBLE_RADIUS)
    )
    name = decode.decode_name(read.classify_fields(name_fields, scale))
    phone = decode.decode_survey_number(read.classify_fields(number_fields, scale))
    return SurveyReading(
        score=score,
        frame=frame,
        name=name,
        phone=phone,
        matching_key=decode.matching_key(name, phone),
    )


def read_identity(image, frame, scale):
    """성명·전화 격자 → (이름, 뒷4자리). 각각 못 읽으면 그쪽만 None.

    `scale` 은 **답란에서 잰 그 장의 연필 세기**다. 성명 열은 14~19칸에 마킹이
    하나, 전화 열은 10칸에 하나뿐이라 그 안에서는 필압의 눈금이 안 나온다 —
    같은 연필이 쓴 답란에서 눈금을 빌려 온다.
    """
    name_inks = read.sample_cells(image, frame, card.name_cells(), card.NAME_BUBBLE_RADIUS)
    phone_inks = read.sample_cells(
        image, frame, card.phone_cells(), card.PHONE_BUBBLE_RADIUS
    )
    name = decode.decode_name(read.classify_fields(group_by_row(name_inks), scale))
    phone = decode.decode_phone(read.classify_fields(group_by_row(phone_inks), scale))
    return name, phone


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

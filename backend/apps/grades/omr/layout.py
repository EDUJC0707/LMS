"""판형 설계 — **우리가 찍는 카드의 원본**. 그림도 리더 좌표도 여기서 나온다.

`card.py` 와 역할이 다르다. `card.py` 는 **남의 카드(튜터시스템 2012)를 재서 적은
측정값**이고, 이 파일은 **우리가 정한 설계값**이다. 그래서 여기엔 보정 상수가
없다 — 보정은 "설계와 실물이 다를 때" 메우는 값인데, 우리가 그리는 카드는
설계가 곧 실물이다.

## 좌표계 — 마커 span 대비 비율

리더는 마커 네 점으로 **호모그래피**를 푼다. 배율(균일·비균일)·회전·사다리꼴이
전부 흡수되므로 **절대 mm 는 맞출 필요가 없다.** 3% 작게 인쇄돼도 정확히 읽힌다.

흡수되지 않는 것은 **마커 span 대비 비율**뿐이다. 그래서 이 파일의 모든 좌표는
(0,0)=좌상 마커, (1,1)=우하 마커인 정규좌표다. mm 는 그릴 때 한 번만 곱한다.

절대 치수가 걸리는 자리는 둘뿐이다(설계 문서 §3):
- 버블이 펜으로 칠할 만큼 커야 한다 — 2.32 x 4.22mm, 실물 65장에서 검증된 크기
- 인쇄기가 마커를 자르면 안 된다 — 가장자리에서 7mm 안쪽

## 판형 막대 — 지면이 자기가 뭔지 말한다

수능 답안지는 가장자리 막대 **개수**로 카드를 구분한다(국어1 … 제2외국어6,
좌우 대칭, 8장 실측에서 y 가 한 픽셀도 안 틀렸다). 방식은 좋은데 **1진**이라
막대 하나가 빠지면 탐구(5)가 한국사(4)로 조용히 읽힌다.

그래서 **자리를 고정하고 2진으로 적는다.** 앵커 두 개(첫·끝)는 항상 찍으므로
간격을 역산해 각 슬롯의 y 를 알 수 있고, 빠진 막대가 "빈 슬롯"으로 드러난다.
개수만 세는 방식으로는 못 하는 구분이다.
"""
from decimal import Decimal

MM = Decimal("25.4")

# --- 용지·프레임 -----------------------------------------------------------
#: A4 가로. 온라인 인쇄 발주라 규격 용지여야 하고, 스캐너 급지도 이 크기다.
PAGE_W_MM = Decimal("297")
PAGE_H_MM = Decimal("210")

#: 마커 중심. 옛 카드 실측(200dpi 2339x1654 렌더의 56.5/2280, 88.5/1582)을
#: mm 로 옮긴 값이다 — 판형을 새로 그려도 **프레임은 물려받는다.** 스캐너·급지·
#: 발주 규격이 이미 이 자리에 맞춰져 있고, 바꿔서 얻을 것이 없다.
MARK_X_MM = (Decimal("7.176"), Decimal("289.560"))
MARK_Y_MM = (Decimal("11.240"), Decimal("200.914"))

#: 마커 자체의 크기(옛 카드와 동일 — 검출기가 이 크기에 맞춰져 있다).
MARK_W_MM = Decimal("1.27")
MARK_H_MM = Decimal("2.41")

SPAN_X_MM = MARK_X_MM[1] - MARK_X_MM[0]
SPAN_Y_MM = MARK_Y_MM[1] - MARK_Y_MM[0]


def to_mm(u, v):
    """정규좌표 -> 지면 mm(좌하 원점, PDF 좌표계)."""
    x = MARK_X_MM[0] + Decimal(str(u)) * SPAN_X_MM
    y_top = MARK_Y_MM[0] + Decimal(str(v)) * SPAN_Y_MM
    return x, PAGE_H_MM - y_top


def mm_to_u(mm):
    return Decimal(str(mm)) / SPAN_X_MM


def mm_to_v(mm):
    return Decimal(str(mm)) / SPAN_Y_MM


# --- 버블 -----------------------------------------------------------------
#: 세로로 긴 스타디움. 실물 65장에서 인쇄 테두리를 직접 재 검증된 치수다.
BUBBLE_W_MM = Decimal("2.324")
BUBBLE_H_MM = Decimal("4.216")
BUBBLE_RU = mm_to_u(BUBBLE_W_MM / 2)
BUBBLE_RV = mm_to_v(BUBBLE_H_MM / 2)

#: 인쇄 선 굵기. 0.3pt(0.106mm)로 그렸더니 200dpi 렌더에서 링이 **조각났고**
#: 옵셋 최소 선폭(약 0.1mm)에도 걸쳐 아예 안 찍힐 수 있었다. 0.18mm 면 링 안쪽
#: 여백이 0.99mm 라 리더의 65% 표본(±0.76mm)을 침범하지 않는다.
STROKE_MM = Decimal("0.18")

#: 격자 간격 — 옛 카드 실측을 **span 에서 역산**한 값이다(65px 는 반올림된
#: 어림이고 실제는 (1467-241)/19 = 64.53px). 어림을 쓰면 20행째에서 0.75mm 밀린다.
ROW_PITCH_MM = Decimal("8.1948")
CHOICE_PITCH_MM = Decimal("5.2070")


# --- 판형 막대 -------------------------------------------------------------
#: 수능 실측 그대로: 13x90px @300dpi, 간격 120px.
BAR_W_MM = Decimal("1.10")
BAR_H_MM = Decimal("7.62")
BAR_PITCH_MM = Decimal("10.16")
BAR_SLOTS = 8
#: 첫 슬롯 중심 y(지면 위에서). 마커 아래로 충분히 떨어뜨려 검출이 안 섞이게 한다.
BAR_TOP_MM = Decimal("108.7")
#: 좌우 가장자리에서의 x 중심 — 마커보다 바깥이 아니라 **같은 열**에 둔다.
BAR_X_MM = (MARK_X_MM[0], MARK_X_MM[1])

ANCHOR_SLOTS = (0, BAR_SLOTS - 1)
DATA_SLOTS = tuple(range(1, BAR_SLOTS - 2))  # 1..5 = 5비트
PARITY_SLOT = BAR_SLOTS - 2  # 6


def encode_bars(layout_id):
    """판형 id -> 슬롯별 채움 여부. 앵커 2 + 데이터 5비트 + 짝수 패리티."""
    if not 0 <= layout_id < (1 << len(DATA_SLOTS)):
        raise ValueError(f"판형 id 가 {len(DATA_SLOTS)}비트를 넘는다: {layout_id}")
    slots = [False] * BAR_SLOTS
    for slot in ANCHOR_SLOTS:
        slots[slot] = True
    for bit, slot in enumerate(DATA_SLOTS):
        slots[slot] = bool(layout_id >> bit & 1)
    slots[PARITY_SLOT] = sum(slots[s] for s in DATA_SLOTS) % 2 == 1
    return slots


def decode_bars(slots):
    """슬롯 -> 판형 id. 앵커나 패리티가 안 맞으면 None(그 장은 보류)."""
    if len(slots) != BAR_SLOTS:
        return None
    if not all(slots[s] for s in ANCHOR_SLOTS):
        return None
    if sum(slots[s] for s in DATA_SLOTS) % 2 != int(bool(slots[PARITY_SLOT])):
        return None
    return sum(bool(slots[slot]) << bit for bit, slot in enumerate(DATA_SLOTS))


# --- 판형 계열 -------------------------------------------------------------
#: 답란 1열 **1번 선택지의 중심**. 아래 mm 값은 전부 **좌상 마커 기준**이다
#: (지면 모서리 기준이 아니다 — `mm_to_u/v` 가 마커 기준 거리를 받는다. 지면
#: 모서리로 적으면 u 가 4.5mm, v 가 11.2mm 밀린다 — 버블 폭보다 큰 오차다).
#: 옛 카드 실측 `ANSWER_CHOICE_X[0]`·`ANSWER_ROW_Y[0]` 에서 마커 원점을 뺀 값이라
#: **1열은 옛 카드와 같은 자리에 찍힌다.** 늘어나는 것은 2열부터다.
ANSWER_COL_X_MM = Decimal("147.0025")
ANSWER_FIRST_ROW_MM = Decimal("19.3675")
ANSWER_COL_PITCH_MM = Decimal("36.8")
ANSWER_ROWS_PER_COL = 20

#: 조사 카드 점수칸 — 십의 자리 1~5, 일의 자리 1~9,0.
SURVEY_TENS = ("1", "2", "3", "4", "5")
SURVEY_ONES = ("1", "2", "3", "4", "5", "6", "7", "8", "9", "0")


class Layout:
    """카드 한 종. `questions=None` 이면 성적 조사 카드다."""

    def __init__(self, layout_id, name, questions=None):
        self.layout_id = layout_id
        self.name = name
        self.questions = questions

    @property
    def is_survey(self):
        return self.questions is None

    @property
    def columns(self):
        if self.is_survey:
            return 0
        return -(-self.questions // ANSWER_ROWS_PER_COL)

    def answer_cells(self):
        """{문항번호: [(u, v)] * 5} — 열이 차면 다음 열로 넘어간다."""
        cells = {}
        for index in range(self.questions or 0):
            col, row = divmod(index, ANSWER_ROWS_PER_COL)
            x0 = ANSWER_COL_X_MM + col * ANSWER_COL_PITCH_MM
            y = ANSWER_FIRST_ROW_MM + row * ROW_PITCH_MM
            cells[index + 1] = [
                (float(mm_to_u(x0 + choice * CHOICE_PITCH_MM)), float(mm_to_v(y)))
                for choice in range(5)
            ]
        return cells

    def bars(self):
        return encode_bars(self.layout_id)


LAYOUTS = (
    Layout(1, "답안20", 20),
    Layout(2, "답안25", 25),
    Layout(3, "답안30", 30),
    Layout(4, "답안35", 35),
    Layout(5, "답안40", 40),
    Layout(6, "성적조사"),
)

BY_ID = {layout.layout_id: layout for layout in LAYOUTS}
BY_NAME = {layout.name: layout for layout in LAYOUTS}


# --- 신원란 — 옛 카드에서 그대로 물려받는다 (대표 2026-08-18 "지금대로") -----
#
# 아래 값은 옛 카드 실측(`card.py`)의 정규좌표 그대로다. 자모 격자를 유지하기로
# 했으므로 **다시 설계하지 않고 물려받는다** — 같은 자리에 찍으면 지난 스캔과
# 새 스캔이 같은 좌표를 쓰고, 리더의 신원란 코드는 한 줄도 안 바뀐다.
#
# 원 단위는 "평균판 px"(마커 사각형을 2223.5x1493.5 로 편 렌더)라 폭으로 나누면
# 곧 정규좌표다.
_AVG_W, _AVG_H = Decimal("2223.5"), Decimal("1493.5")

NAME_COL_U = tuple(
    Decimal(str(x)) / _AVG_W
    for x in (87.4, 128.5, 171.1, 220.2, 261.3, 303.9,
              355.9, 397.1, 439.6, 495.8, 536.9, 579.4)
)
NAME_ROW_V = (Decimal("694.0") / _AVG_H, Decimal("1391.5") / _AVG_H)
NAME_ROWS = 19
NAME_CONSONANT_ROWS = 14
NAME_VOWEL_COLUMNS = (2, 5, 8, 11)
#: 성명 버블은 스타디움이 아니라 지름 ~31px 정원이다.
NAME_BUBBLE_D_MM = Decimal("31.0") / _AVG_W * SPAN_X_MM

PHONE_COL_U = tuple(
    Decimal(str(x)) / _AVG_W for x in (706.9, 759.8, 839.0, 896.1)
)
PHONE_ROW_V = (Decimal("698.7") / _AVG_H, Decimal("1149.2") / _AVG_H)
PHONE_DIGITS = 10

#: 초성·종성 14자 / 중성 19자 — 지면에 찍는 글자.
CONSONANTS = ("ㄱ", "ㄴ", "ㄷ", "ㄹ", "ㅁ", "ㅂ", "ㅅ",
              "ㅇ", "ㅈ", "ㅊ", "ㅋ", "ㅌ", "ㅍ", "ㅎ")
VOWELS = ("ㅏ", "ㅐ", "ㅑ", "ㅒ", "ㅓ", "ㅔ", "ㅕ", "ㅖ", "ㅗ", "ㅘ",
          "ㅙ", "ㅚ", "ㅛ", "ㅜ", "ㅝ", "ㅞ", "ㅟ", "ㅠ", "ㅡ")


def _even(span, count):
    first, last = span
    step = (last - first) / (count - 1)
    return [first + step * index for index in range(count)]


def name_cells():
    """{(열, 행): (u, v)} — 모음 열은 19행, 나머지는 14행. 8x14 + 4x19 = 188."""
    vs = _even(NAME_ROW_V, NAME_ROWS)
    return {
        (col, row): (float(NAME_COL_U[col - 1]), float(vs[row - 1]))
        for col in range(1, len(NAME_COL_U) + 1)
        for row in range(1, (NAME_ROWS if col in NAME_VOWEL_COLUMNS else NAME_CONSONANT_ROWS) + 1)
    }


def phone_cells():
    """{(자리, 숫자): (u, v)} — 4자리 x 0~9 = 40."""
    vs = _even(PHONE_ROW_V, PHONE_DIGITS)
    return {
        (pos, digit): (float(PHONE_COL_U[pos - 1]), float(vs[digit]))
        for pos in range(1, len(PHONE_COL_U) + 1)
        for digit in range(PHONE_DIGITS)
    }

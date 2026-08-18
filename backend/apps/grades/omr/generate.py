"""카드 생성기 — `layout.py` 하나에서 **인쇄용 PDF** 와 **리더 좌표**를 함께 뽑는다.

이게 이 작업의 본체다. 지금 `card.py` 는 남의 카드를 재서 적은 **측정값**이라
판형과 리더가 어긋날 수 있었고, 실제로 어긋나서 보정 상수(`CALIBRATION_U/V`)가
생겼다. 생성기가 둘을 같이 뱉으면 **어긋날 수가 없다** — 같은 숫자로 그리고 같은
숫자로 읽는다.

    layout.py ──┬──▶ omr-답안25.pdf   (인쇄 발주)
                └──▶ 리더 좌표         (같은 모듈을 import 한다)

## 지면은 옛 카드를 그대로 옮긴다 (대표 2026-08-18)

*"최대한 우리 기본 OMR 비슷하게, 문제가 늘어나는 건 수능 principle 대로"* ·
*"있는거 그대로 font 최대한 맞춰서"*.

그래서 박스 자리·문구·초록 색조(#C3E9C2)를 옛 카드 실측에서 가져왔다. 학생과
조교가 몇 년째 보던 지면이라 **낯설게 만들 이유가 없다.** 새로운 것은 두 가지뿐:
문항이 늘면 수능처럼 **열이 늘고**, 가장자리에 **판형 막대**가 붙는다.

## 왜 reportlab 인가

한글 라벨(자모 19자·안내문)을 벡터로 찍어야 하는데 `pypdf` 는 읽고 쓰는 도구지
그리는 도구가 아니다. reportlab 은 `UnicodeCIDFont('HYGothic-Medium')` 로 폰트
파일 없이 한글이 나온다.

## 인쇄 주의

- **배율 조정 없이(100%) 인쇄한다.** 호모그래피가 배율을 흡수하므로 판독은
  되지만, 축소되면 버블이 펜보다 작아진다
- 마커·판형 막대는 **검정 단색**이다
"""
import io

from reportlab.lib.colors import Color, black, white
from reportlab.lib.units import mm as MM_UNIT
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

from . import layout as L

FONT = "HYGothic-Medium"
_FONT_READY = False

#: 옛 카드 실측 색. 초록 색조는 라벨칸·안내 박스에만 쓴다.
TINT = Color(195 / 255, 233 / 255, 194 / 255)
INK = Color(35 / 255, 31 / 255, 32 / 255)

#: 박스 자리 — 옛 카드 200dpi 렌더에서 잰 정규좌표 그대로.
BOX_SCHOOL = (0.025, 0.210, 0.272, 0.310)
BOX_NAME = (0.025, 0.326, 0.273, 0.967)
BOX_RULES = (0.294, 0.069, 0.420, 0.312)
BOX_PHONE = (0.294, 0.329, 0.421, 0.812)
BOX_PHONE_HOW = (0.295, 0.823, 0.421, 0.967)
BOX_ANSWER_V = (0.022, 0.967)
DIVIDER_U = (0.448, 0.462)

#: 옛 카드 문구 그대로.
RULES_TITLE = "지켜야 할 사항"
RULES = [
    ("1. 반드시 검정색 싸인펜으로 표기", 0),
    ("합니다.", 1),
    ("※ 샤프펜슬, 볼펜 사용시 불이익 발생", 2),
    ("", 0),
    ("2. 표기란에는     와 같이 바르게", 0),
    ("표기해야 합니다.", 1),
    ("(잘못된 표기 예시)", 3),
]
RULES_TAIL = [("3. 수정시에는 수정테이프만을", 0), ("사용하여 깨끗하게 수정합니다.", 1)]

PHONE_HOW_TITLE = "전화번호 마킹방법"
PHONE_HOW = [
    ("1. 학생 혹은 학부모 전화번호 끝 4자리", 0),
    ("를 마킹합니다.", 1),
    ("", 0),
    ("2. 전화번호에  0  있는 경우에도 모두", 0),
    ("마킹합니다.", 1),
    ("", 0),
    ("예시)  0 5 0 1 인 경우에는 차례대로", 2),
    ("0 5 0 1 을  마킹합니다.", 3),
]


def _font():
    global _FONT_READY
    if not _FONT_READY:
        pdfmetrics.registerFont(UnicodeCIDFont(FONT))
        _FONT_READY = True
    return FONT


def _stroke():
    """인쇄 선 굵기(pt). 너무 얇으면 인쇄가 먹지 않고 링이 조각난다."""
    return float(L.STROKE_MM) * MM_UNIT


def _xy(u, v):
    """정규좌표 -> reportlab 포인트(좌하 원점)."""
    x_mm, y_mm = L.to_mm(u, v)
    return float(x_mm) * MM_UNIT, float(y_mm) * MM_UNIT


def _rect(pen, u0, v0, u1, v1, fill=None, radius=None, width=None):
    x0, y0 = _xy(u0, v0)
    x1, y1 = _xy(u1, v1)
    pen.setLineWidth(width if width is not None else _stroke() * 2.2)
    if fill is not None:
        pen.setFillColor(fill)
    pen.roundRect(
        x0, y1, x1 - x0, y0 - y1,
        radius if radius is not None else 2.0,
        stroke=1, fill=1 if fill is not None else 0,
    )
    pen.setFillColor(INK)


def _text(pen, u, v, body, size=5.0, anchor="middle"):
    x, y = _xy(u, v)
    pen.setFont(_font(), size)
    draw = {"middle": pen.drawCentredString, "left": pen.drawString,
            "right": pen.drawRightString}[anchor]
    draw(x, y - size * 0.36, body)


def _fit(body, size, room_u):
    """박스 폭을 넘지 않는 글자 크기. 손으로 맞추면 문구가 조금만 길어져도 삐져나온다."""
    room_pt = room_u * float(L.SPAN_X_MM) * MM_UNIT
    width = pdfmetrics.stringWidth(body, _font(), size)
    return size if width <= room_pt else max(size * room_pt / width, 3.2)


def _fitted(pen, u, v, body, size, room_u, anchor="left"):
    _text(pen, u, v, body, size=_fit(body, size, room_u), anchor=anchor)


def _bubble(pen, u, v, width_mm, height_mm):
    """스타디움(세로로 긴 둥근 사각형) 테두리 한 칸."""
    x, y = _xy(u, v)
    w = float(width_mm) * MM_UNIT
    h = float(height_mm) * MM_UNIT
    pen.setLineWidth(_stroke())
    pen.roundRect(x - w / 2, y - h / 2, w, h, min(w, h) / 2, stroke=1, fill=0)


def _filled_bubble(pen, u, v):
    x, y = _xy(u, v)
    w = float(L.BUBBLE_W_MM) * MM_UNIT
    h = float(L.BUBBLE_H_MM) * MM_UNIT
    pen.setFillColor(INK)
    pen.roundRect(x - w / 2, y - h / 2, w, h, w / 2, stroke=0, fill=1)


# --- 지면 부품 -------------------------------------------------------------


def _fiducials(pen):
    """네 귀퉁이 마커 — 리더가 호모그래피를 푸는 네 점이다."""
    pen.setFillColor(black)
    w = float(L.MARK_W_MM) * MM_UNIT
    h = float(L.MARK_H_MM) * MM_UNIT
    for u in (0.0, 1.0):
        for v in (0.0, 1.0):
            x, y = _xy(u, v)
            pen.rect(x - w / 2, y - h / 2, w, h, stroke=0, fill=1)
    pen.setFillColor(INK)


def _layout_bars(pen, card):
    """판형 막대 — 좌우 대칭. 앵커 2 + 데이터 5비트 + 패리티."""
    pen.setFillColor(black)
    w = float(L.BAR_W_MM) * MM_UNIT
    h = float(L.BAR_H_MM) * MM_UNIT
    for slot, filled in enumerate(card.bars()):
        if not filled:
            continue
        y_top = L.BAR_TOP_MM + slot * L.BAR_PITCH_MM
        y = (float(L.PAGE_H_MM) - float(y_top)) * MM_UNIT
        for x_mm in L.BAR_X_MM:
            pen.rect(float(x_mm) * MM_UNIT - w / 2, y - h / 2, w, h, stroke=0, fill=1)
    pen.setFillColor(INK)


def _school_block(pen):
    """학교 / 학원 — 옛 카드 그대로. 라벨칸만 초록."""
    u0, v0, u1, v1 = BOX_SCHOOL
    label_u = u0 + (u1 - u0) * 0.235
    mid_v = (v0 + v1) / 2
    _rect(pen, u0, v0, u1, v1)
    for top, bottom, label in ((v0, mid_v, "학 교"), (mid_v, v1, "학 원")):
        _rect(pen, u0, top, label_u, bottom, fill=TINT, radius=1.0)
        _text(pen, (u0 + label_u) / 2, (top + bottom) / 2, label, size=7.5)
    x0, _ = _xy(label_u, v0)
    x1, y = _xy(u1, mid_v)
    pen.setLineWidth(_stroke() * 2.2)
    pen.line(x0, y, x1, y)
    _text(pen, u1 - 0.008, (v0 + mid_v) / 2, "고등학교", size=7.5, anchor="right")


def _rules_block(pen):
    """지켜야 할 사항 — 문구·잘못된 표기 예시까지 옛 카드 그대로."""
    u0, v0, u1, v1 = BOX_RULES
    _rect(pen, u0, v0, u1, v1, fill=TINT, radius=3.0)
    centre = (u0 + u1) / 2
    _text(pen, centre, v0 + 0.026, RULES_TITLE, size=8.4)
    x0, _ = _xy(u0 + 0.020, 0)
    x1, y = _xy(u1 - 0.020, v0 + 0.038)
    pen.setLineWidth(_stroke())
    pen.line(x0, y, x1, y)

    # 줄 간격을 상수로 박으면 문구가 한 줄 늘 때 조용히 박스 밖으로 나간다.
    # 남은 높이에서 역산한다 — 예시 버블 한 줄은 두 줄 몫으로 센다.
    indents = (0.012, 0.026, 0.020, 0.0)
    body_v0 = v0 + 0.058
    step = (v1 - 0.012 - body_v0) / (len(RULES) + len(RULES_TAIL) + 2)
    v = body_v0
    mark_at = None
    for order, (line, indent) in enumerate(RULES):
        if line.startswith("2. 표기란에는"):
            mark_at = (order, u0 + indents[indent], line.split("에는")[0] + "에는  ")
    for line, indent in RULES:
        if line:
            if indent == 3:
                _fitted(pen, centre, v, line, 5.6, u1 - u0 - 0.010, anchor="middle")
            else:
                start = u0 + indents[indent]
                _fitted(pen, start, v, line, 5.0 if indent == 2 else 5.8,
                        u1 - start - 0.008)
        v += step
    # 2번 문구 안의 올바른 표기 예시 — 줄이 재배치되므로 **그 줄에 붙여서** 그린다.
    # 고정 오프셋으로 두면 문구가 한 줄 늘 때 엉뚱한 줄 위에 얹힌다.
    if mark_at is not None:
        order, start_u, prefix = mark_at
        size = _fit(RULES[order][0], 5.8, u1 - start_u - 0.008)
        offset = pdfmetrics.stringWidth(prefix, _font(), size) / MM_UNIT
        _filled_bubble(pen, start_u + float(L.mm_to_u(offset)), body_v0 + order * step)
    # 잘못된 표기 5종
    for index in range(5):
        _wrong_mark(pen, u0 + 0.028 + index * 0.0175, v + step * 0.55, index)
    v += step * 2
    for line, indent in RULES_TAIL:
        start = u0 + indents[indent]
        _fitted(pen, start, v, line, 5.8, u1 - start - 0.008)
        v += step


def _wrong_mark(pen, u, v, kind):
    """잘못된 표기 예시 — 옛 카드의 다섯 가지(V·X·점·세로줄·빗금)."""
    _bubble(pen, u, v, float(L.BUBBLE_W_MM) * 1.15, float(L.BUBBLE_H_MM) * 1.05)
    x, y = _xy(u, v)
    w = float(L.BUBBLE_W_MM) * 1.15 * MM_UNIT / 2
    h = float(L.BUBBLE_H_MM) * 1.05 * MM_UNIT / 2
    pen.setLineWidth(_stroke() * 1.6)
    if kind == 0:
        pen.line(x - w * 0.6, y + h * 0.6, x, y - h * 0.5)
        pen.line(x, y - h * 0.5, x + w * 0.6, y + h * 0.6)
    elif kind == 1:
        pen.line(x - w * 0.6, y + h * 0.5, x + w * 0.6, y - h * 0.5)
        pen.line(x - w * 0.6, y - h * 0.5, x + w * 0.6, y + h * 0.5)
    elif kind == 2:
        pen.setFillColor(INK)
        pen.circle(x, y, w * 0.42, stroke=0, fill=1)
    elif kind == 3:
        pen.line(x, y + h * 0.65, x, y - h * 0.65)
    else:
        for offset in (-0.5, 0.15):
            pen.line(x - w * 0.6, y + h * offset, x + w * 0.6, y + h * (offset + 0.85))


def _titled_grid_box(pen, box, title, grid_v0):
    """성명·전화 공용 — 초록 제목칸 + 손글씨 줄 + (버블 격자는 호출자가)."""
    u0, v0, u1, v1 = box
    _rect(pen, u0, v0, u1, v1)
    header_v = v0 + 0.048
    _rect(pen, u0, v0, u1, header_v, fill=TINT, radius=1.0)
    _text(pen, (u0 + u1) / 2, (v0 + header_v) / 2, title, size=7.2)
    write_v = grid_v0 - 0.030
    x0, _ = _xy(u0, 0)
    x1, y = _xy(u1, write_v)
    pen.setLineWidth(_stroke() * 2.2)
    pen.line(x0, y, x1, y)


def _name_block(pen):
    """성명 자모 격자 — 8열x14행(초·종성) + 4열x19행(중성) = 188칸."""
    _titled_grid_box(pen, BOX_NAME, "성    명    (좌측부터 차례로 마킹)",
                     float(L.NAME_ROW_V[0]))
    diameter = L.NAME_BUBBLE_D_MM
    for (col, row), (u, v) in L.name_cells().items():
        letters = L.VOWELS if col in L.NAME_VOWEL_COLUMNS else L.CONSONANTS
        _bubble(pen, u, v, diameter, diameter)
        _text(pen, u, v, letters[row - 1], size=3.5)


def _phone_block(pen):
    """전화번호 끝 네 자리 — 4열 x 0~9. 가운데가 넓은 건 구분선 자리다."""
    _titled_grid_box(pen, BOX_PHONE, "전화번호  끝  네  자리", float(L.PHONE_ROW_V[0]))
    for (_pos, digit), (u, v) in L.phone_cells().items():
        _bubble(pen, u, v, L.BUBBLE_W_MM, L.BUBBLE_H_MM)
        _text(pen, u, v, str(digit), size=3.4)

    u0, v0, u1, v1 = BOX_PHONE_HOW
    _rect(pen, u0, v0, u1, v1, fill=TINT, radius=3.0)
    _text(pen, (u0 + u1) / 2, v0 + 0.023, PHONE_HOW_TITLE, size=7.4)
    x0, _ = _xy(u0 + 0.018, 0)
    x1, y = _xy(u1 - 0.018, v0 + 0.034)
    pen.setLineWidth(_stroke())
    pen.line(x0, y, x1, y)
    v = v0 + 0.048
    step = (v1 - 0.010 - v) / (len(PHONE_HOW) - 1)
    for line, indent in PHONE_HOW:
        if line:
            start = u0 + (0.010, 0.021, 0.016, 0.030)[indent]
            _fitted(pen, start, v, line, 4.9, u1 - start - 0.008)
        v += step


def _divider(pen):
    """세로 구분바 — 신원란과 답란을 가르는 옛 카드의 초록 띠."""
    u0, u1 = DIVIDER_U
    _rect(pen, u0, BOX_ANSWER_V[0], u1, BOX_ANSWER_V[1], fill=TINT, radius=2.0)


def _answer_block(pen, card):
    """답란 — 20행이 차면 다음 열(수능 방식). 열 1은 옛 카드와 같은 자리다."""
    cells = card.answer_cells()
    width = float(L.mm_to_u(L.ANSWER_COL_PITCH_MM))
    first_u = float(L.mm_to_u(L.ANSWER_COL_X_MM))
    for col in range(card.columns):
        u0 = first_u - 0.041 + col * width
        u1 = u0 + width
        _rect(pen, u0, BOX_ANSWER_V[0], u1, BOX_ANSWER_V[1])
        header_v = BOX_ANSWER_V[0] + 0.040
        _rect(pen, u0, BOX_ANSWER_V[0], u1, header_v, fill=TINT, radius=1.0)
        number_u = u0 + 0.026
        _text(pen, (u0 + number_u) / 2, (BOX_ANSWER_V[0] + header_v) / 2, "문번", size=5.6)
        _text(pen, (number_u + u1) / 2, (BOX_ANSWER_V[0] + header_v) / 2, "답    란", size=5.6)
        x0, ytop = _xy(number_u, BOX_ANSWER_V[0])
        _, ybot = _xy(number_u, BOX_ANSWER_V[1])
        pen.setLineWidth(_stroke() * 2.2)
        pen.line(x0, ytop, x0, ybot)

    for question, choices in cells.items():
        for index, (u, v) in enumerate(choices, start=1):
            _bubble(pen, u, v, L.BUBBLE_W_MM, L.BUBBLE_H_MM)
            _text(pen, u, v, str(index), size=3.0)
        _text(pen, choices[0][0] - 0.0245, choices[0][1], str(question), size=5.4)


def _survey_block(pen):
    """성적 조사 — 점수 두 자리(십 1~5 · 일 1~9,0) + ★내 점수★ 손글씨 칸."""
    width = float(L.mm_to_u(L.ANSWER_COL_PITCH_MM))
    u0 = float(L.mm_to_u(L.ANSWER_COL_X_MM)) - 0.041
    u1 = u0 + width
    _rect(pen, u0, BOX_ANSWER_V[0], u1, BOX_ANSWER_V[1])
    header_v = BOX_ANSWER_V[0] + 0.040
    _rect(pen, u0, BOX_ANSWER_V[0], u1, header_v, fill=TINT, radius=1.0)
    _text(pen, (u0 + u1) / 2, (BOX_ANSWER_V[0] + header_v) / 2, "점        수", size=6.4)

    top_v = float(L.mm_to_v(L.ANSWER_FIRST_ROW_MM)) + 0.030
    step_v = float(L.mm_to_v(L.ROW_PITCH_MM))
    centre = (u0 + u1) / 2
    gap = float(L.mm_to_u(L.CHOICE_PITCH_MM)) * 2.2
    for column, digits in enumerate((L.SURVEY_TENS, L.SURVEY_ONES)):
        u = centre + (column - 0.5) * gap
        _text(pen, u, top_v - 0.026, "십" if column == 0 else "일", size=6.0)
        for row, digit in enumerate(digits):
            v = top_v + row * step_v
            _bubble(pen, u, v, L.BUBBLE_W_MM, L.BUBBLE_H_MM)
            _text(pen, u, v, digit, size=3.4)

    # ★내 점수★ — 94장 중 34장이 버블을 안 칠하고 여기에만 적었다(설계 문서 §7).
    bu0, bu1 = u1 + 0.030, u1 + 0.030 + width
    _rect(pen, bu0, BOX_ANSWER_V[0], bu1, BOX_ANSWER_V[0] + 0.040, fill=TINT, radius=1.0)
    _rect(pen, bu0, BOX_ANSWER_V[0], bu1, BOX_ANSWER_V[0] + 0.320)
    _text(pen, (bu0 + bu1) / 2, BOX_ANSWER_V[0] + 0.020, "★ 내 점수 ★", size=7.0)


def render(card, title="한종철 생명과학", subtitle=""):
    """카드 한 장을 PDF 바이트로. `card` 는 `layout.Layout`."""
    buffer = io.BytesIO()
    page = (float(L.PAGE_W_MM) * MM_UNIT, float(L.PAGE_H_MM) * MM_UNIT)
    pen = canvas.Canvas(buffer, pagesize=page)
    pen.setTitle(f"{title} — {card.name}")
    pen.setFillColor(white)
    pen.rect(0, 0, page[0], page[1], stroke=0, fill=1)
    pen.setFillColor(INK)
    pen.setStrokeColor(INK)

    _fiducials(pen)
    _layout_bars(pen, card)
    _school_block(pen)
    _rules_block(pen)
    _name_block(pen)
    _phone_block(pen)
    _divider(pen)
    if card.is_survey:
        _survey_block(pen)
    else:
        _answer_block(pen, card)

    _text(pen, 0.010, 0.030, title, size=11, anchor="left")
    if subtitle:
        _text(pen, 0.010, 0.066, subtitle, size=7.5, anchor="left")
    _text(pen, 0.992, 0.030, card.name, size=7.5, anchor="right")

    pen.showPage()
    pen.save()
    return buffer.getvalue()

"""카드 생성기 — `layout.py` 하나에서 **인쇄용 PDF** 와 **리더 좌표**를 함께 뽑는다.

지금 `card.py` 는 남의 카드를 재서 적은 **측정값**이라 판형과 리더가 어긋날 수
있었고, 실제로 어긋나서 보정 상수(`CALIBRATION_U/V`)가 생겼다. 생성기가 둘을
같이 뱉으면 **어긋날 수가 없다** — 같은 숫자로 그리고 같은 숫자로 읽는다.

## 지면은 옛 카드를 그대로 옮긴다 (대표 2026-08-18)

*"최대한 우리 기본 OMR 비슷하게, 문제가 늘어나는 건 수능 principle 대로"* ·
*"있는거 그대로"*. 그래서 박스 자리·문구·**색**을 옛 카드 실측에서 가져왔다.

옛 카드는 흑백이 아니라 **2도 인쇄**다(200dpi 렌더 최빈색):

| | 값 | 어디에 |
|---|---|---|
| 분홍 | `#EE266D` | 버블 링과 그 안의 숫자 |
| 진초록 | `#1D753F` | 문번·머리글 — 구조 |
| 연초록 | `#C3E9C2` | 라벨칸·안내 박스 바탕 |
| 먹 | `#231F20` | 본문 |

**버블이 분홍인 것은 장식이 아니다.** 검정 사인펜 마킹과 인쇄된 링이 같은 색이면
사람도 기계도 둘을 가르기 어렵다.

## 로고

옛 카드 로고는 **맞춰 그린 레터마크**라 시스템 폰트로 흉내 낼 수 없다. 빈 카드
PDF 에서 1200dpi 로 떠 `assets/logo.png` 에 두고 그대로 얹는다.

## 글자

한글 CID 폰트는 라틴을 **전각**으로 낸다 — `2027 OMEGA black 3회` 를 통째로
넘기면 `OMEGA` 가 뭉개진다(대표 지적). 그래서 스크립트별로 잘라 라틴은
Helvetica, 한글은 CID 폰트로 그린다(`_runs`).

## 인쇄 주의

- **배율 조정 없이(100%) 인쇄한다.** 호모그래피가 배율을 흡수하므로 판독은
  되지만, 축소되면 버블이 펜보다 작아진다
- 마커·판형 막대는 **검정 단색**이다
"""
import io
import pathlib

from reportlab.lib.colors import Color, black, white  # noqa: F401
from reportlab.lib.units import mm as MM_UNIT
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

from . import layout as L

FONT = "HYGothic-Medium"
LATIN = "Helvetica"
LATIN_BOLD = "Helvetica-Bold"
_FONT_READY = False

LOGO = pathlib.Path(__file__).parent / "assets" / "logo.png"

#: 옛 카드 실측 색.
PINK = Color(0xEE / 255, 0x26 / 255, 0x6D / 255)
GREEN = Color(0x1D / 255, 0x75 / 255, 0x3F / 255)
TINT = Color(0xC3 / 255, 0xE9 / 255, 0xC2 / 255)
INK = Color(0x23 / 255, 0x1F / 255, 0x20 / 255)

#: 버블 안 글자 — 옛 카드에서 링 높이의 약 40% 다. 작게 그렸더니 원본보다
#: 눈에 띄게 작았다(대표 지적). 리더 입장에서도 **원본과 같은 크기가 안전하다**:
#: 상대화 문턱이 이 글리프가 인쇄된 지면에서 맞춰졌다.
CELL_GLYPH_PT = 6.0
NAME_GLYPH_PT = 6.0

#: 박스 자리 — 옛 카드 200dpi 렌더에서 잰 정규좌표 그대로.
BOX_SCHOOL = (0.025, 0.210, 0.272, 0.310)
BOX_NAME = (0.025, 0.326, 0.273, 0.967)
BOX_RULES = (0.294, 0.069, 0.420, 0.312)
BOX_PHONE = (0.294, 0.329, 0.421, 0.812)
BOX_PHONE_HOW = (0.295, 0.823, 0.421, 0.967)
BOX_ANSWER_V = (0.022, 0.967)
DIVIDER_U = (0.448, 0.462)
NUMBER_COL_U = 0.030

HEAD_EXAM_V = 0.030
HEAD_LOGO_V = 0.150
HEAD_U = 0.012

#: 5문항마다 구분선 — 옛 카드에 있다. 20줄이 한 덩어리면 줄을 잘못 탄다.
GROUP_EVERY = 5

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

SURVEY_HOW_TITLE = "점수 마킹방법"
SURVEY_HOW = [
    ("1. 학교에서 본 모의고사 점수를", 0),
    ("십의 자리·일의 자리로 마킹합니다.", 1),
    ("", 0),
    ("2. 버블을 칠하지 않으면 위 칸의", 0),
    ("손글씨로 읽습니다.", 1),
]

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


# --- 글자 ------------------------------------------------------------------


def _runs(body):
    """문자열을 (덩어리, 라틴인가)로 자른다.

    한글 CID 폰트는 라틴을 전각으로 내서 `OMEGA` 자간이 뭉개진다. 잘라서 라틴만
    Helvetica 로 그리면 제대로 잡힌다.
    """
    runs, current, latin = [], "", None
    for char in body:
        is_latin = char.isascii()
        if latin is None or is_latin == latin:
            current += char
        else:
            runs.append((current, latin))
            current = char
        latin = is_latin
    if current:
        runs.append((current, latin))
    return runs


def _face(is_latin, bold):
    if is_latin:
        return LATIN_BOLD if bold else LATIN
    return _font()


def _width(body, size, bold=False):
    return sum(
        pdfmetrics.stringWidth(chunk, _face(is_latin, bold), size)
        for chunk, is_latin in _runs(body)
    )


def _text(pen, u, v, body, size=5.0, anchor="middle", colour=None, bold=False):
    """한 줄 그리기. `bold` 는 획을 덧그려 굵힌다.

    빈 카드는 NanumGothicBold·MalgunGothicBold 로 짜여 있는데(PDF 폰트 목록
    실측) reportlab 의 한글 CID 폰트에는 볼드 자족이 없다. 폰트 파일을 들고
    다니는 대신 **채우고 나서 같은 색으로 한 번 두르면** 같은 두께가 난다 —
    어느 기계에서 돌려도 결과가 같다.
    """
    x, y = _xy(u, v)
    fill = colour or INK
    pen.setFillColor(fill)
    total = _width(body, size, bold)
    if anchor == "middle":
        x -= total / 2
    elif anchor == "right":
        x -= total
    y -= size * 0.36
    if bold:
        pen.setStrokeColor(fill)
        pen.setLineWidth(size * 0.045)
    for chunk, is_latin in _runs(body):
        face = _face(is_latin, bold)
        text = pen.beginText(x, y)
        text.setFont(face, size)
        # 텍스트 객체는 캔버스의 색을 물려받지 않는다 — 여기서 다시 준다.
        # (안 주면 흰 글자가 검게 나온다: 채운 버블 위 예시 숫자가 그랬다.)
        text.setFillColor(fill)
        if bold:
            text.setStrokeColor(fill)
        text.setTextRenderMode(2 if bold else 0)
        text.textOut(chunk)
        pen.drawText(text)
        x += pdfmetrics.stringWidth(chunk, face, size)
    if bold:
        pen.setStrokeColor(INK)
    pen.setFillColor(INK)


def _fit(body, size, room_u, bold=False):
    """박스 폭을 넘지 않는 글자 크기. 손으로 맞추면 문구가 조금만 길어져도 삐져나온다."""
    room_pt = room_u * float(L.SPAN_X_MM) * MM_UNIT
    width = _width(body, size, bold)
    return size if width <= room_pt else max(size * room_pt / width, 3.2)


def _fitted(pen, u, v, body, size, room_u, anchor="left", colour=None):
    _text(pen, u, v, body, size=_fit(body, size, room_u), anchor=anchor, colour=colour)


# --- 도형 ------------------------------------------------------------------


def _stroke():
    return float(L.STROKE_MM) * MM_UNIT


def _xy(u, v):
    x_mm, y_mm = L.to_mm(u, v)
    return float(x_mm) * MM_UNIT, float(y_mm) * MM_UNIT


def _rect(pen, u0, v0, u1, v1, fill=None, radius=None, edge=None):
    x0, y0 = _xy(u0, v0)
    x1, y1 = _xy(u1, v1)
    pen.setStrokeColor(edge or INK)
    pen.setLineWidth(_stroke() * 2.2)
    if fill is not None:
        pen.setFillColor(fill)
    pen.roundRect(x0, y1, x1 - x0, y0 - y1,
                  radius if radius is not None else 2.0,
                  stroke=1, fill=1 if fill is not None else 0)
    pen.setFillColor(INK)
    pen.setStrokeColor(INK)


def _line(pen, u0, v0, u1, v1, colour=None, weight=2.2):
    x0, y0 = _xy(u0, v0)
    x1, y1 = _xy(u1, v1)
    pen.setStrokeColor(colour or INK)
    pen.setLineWidth(_stroke() * weight)
    pen.line(x0, y0, x1, y1)
    pen.setStrokeColor(INK)


def _bubble(pen, u, v, width_mm, height_mm, colour=None):
    """스타디움 테두리 한 칸. 기본은 분홍 — 검정 마킹과 색으로 갈린다."""
    x, y = _xy(u, v)
    w = float(width_mm) * MM_UNIT
    h = float(height_mm) * MM_UNIT
    pen.setStrokeColor(colour or PINK)
    pen.setLineWidth(_stroke())
    pen.roundRect(x - w / 2, y - h / 2, w, h, min(w, h) / 2, stroke=1, fill=0)
    pen.setStrokeColor(INK)


def _cell(pen, u, v, glyph, width_mm=None, height_mm=None, size=None):
    _bubble(pen, u, v, width_mm or L.BUBBLE_W_MM, height_mm or L.BUBBLE_H_MM)
    _text(pen, u, v, glyph, size=size or CELL_GLYPH_PT, colour=PINK)


def _filled_bubble(pen, u, v):
    x, y = _xy(u, v)
    w = float(L.BUBBLE_W_MM) * MM_UNIT
    h = float(L.BUBBLE_H_MM) * MM_UNIT
    pen.setFillColor(INK)
    pen.roundRect(x - w / 2, y - h / 2, w, h, w / 2, stroke=0, fill=1)
    pen.setFillColor(INK)


# --- 지면 부품 -------------------------------------------------------------


def _fiducials(pen):
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


def _header(pen, title, exam):
    """회차명 + 로고. 회차는 시험을 만들 때 채운다(대표 2026-08-18).

    비우면 손으로 적을 줄을 남긴다 — 미리 찍어 둘 수도 있어야 한다.
    """
    if exam:
        _text(pen, HEAD_U, HEAD_EXAM_V, exam, size=12.0, anchor="left", bold=True)
    else:
        _line(pen, HEAD_U, HEAD_EXAM_V + 0.012, HEAD_U + 0.185,
              HEAD_EXAM_V + 0.012, weight=1.0)
        _text(pen, HEAD_U + 0.193, HEAD_EXAM_V, "회차", size=6.5, anchor="left")

    if LOGO.exists():
        art = ImageReader(str(LOGO))
        width_px, height_px = art.getSize()
        width_mm = 60.0
        height_mm = width_mm * height_px / width_px
        x, y = _xy(HEAD_U, HEAD_LOGO_V)
        pen.drawImage(art, x, y - height_mm * MM_UNIT / 2,
                      width=width_mm * MM_UNIT, height=height_mm * MM_UNIT,
                      mask="auto")
    else:
        _text(pen, HEAD_U, HEAD_LOGO_V, title, size=13, anchor="left")


def _school_block(pen):
    """학교 / 학급 — 옛 카드의 `학원` 자리가 학급이다(대표 2026-08-18)."""
    u0, v0, u1, v1 = BOX_SCHOOL
    label_u = u0 + (u1 - u0) * 0.235
    mid_v = (v0 + v1) / 2
    _rect(pen, u0, v0, u1, v1)
    for top, bottom, label in ((v0, mid_v, "학 교"), (mid_v, v1, "학 급")):
        _rect(pen, u0, top, label_u, bottom, fill=TINT, radius=1.0)
        _text(pen, (u0 + label_u) / 2, (top + bottom) / 2, label,
               size=11.0, colour=GREEN, bold=True)
    _line(pen, label_u, mid_v, u1, mid_v)
    _text(pen, u1 - 0.008, (v0 + mid_v) / 2, "고등학교", size=10.5, anchor="right", bold=True)


def _rules_block(pen):
    u0, v0, u1, v1 = BOX_RULES
    _rect(pen, u0, v0, u1, v1, fill=TINT, radius=3.0)
    centre = (u0 + u1) / 2
    _text(pen, centre, v0 + 0.026, RULES_TITLE, size=11.0, colour=GREEN, bold=True)
    _line(pen, u0 + 0.020, v0 + 0.038, u1 - 0.020, v0 + 0.038, colour=GREEN, weight=1.0)

    indents = (0.012, 0.026, 0.020, 0.0)
    body_v0 = v0 + 0.062
    step = (v1 - 0.012 - body_v0) / (len(RULES) + len(RULES_TAIL) + 2)
    mark_at = None
    for order, (line, indent) in enumerate(RULES):
        if line.startswith("2. 표기란에는"):
            mark_at = (order, u0 + indents[indent], line.split("에는")[0] + "에는  ")
    v = body_v0
    for line, indent in RULES:
        if line:
            if indent == 3:
                _fitted(pen, centre, v, line, 7.2, u1 - u0 - 0.010, anchor="middle")
            else:
                start = u0 + indents[indent]
                _fitted(pen, start, v, line, 6.4 if indent == 2 else 7.2,
                        u1 - start - 0.008)
        v += step
    if mark_at is not None:
        order, start_u, prefix = mark_at
        size = _fit(RULES[order][0], 6.2, u1 - start_u - 0.008)
        offset = _width(prefix, size) / MM_UNIT
        _filled_bubble(pen, start_u + float(L.mm_to_u(offset)), body_v0 + order * step)
    for index in range(5):
        _wrong_mark(pen, u0 + 0.028 + index * 0.0175, v + step * 0.55, index)
    v += step * 2
    for line, indent in RULES_TAIL:
        start = u0 + indents[indent]
        _fitted(pen, start, v, line, 7.2, u1 - start - 0.008)
        v += step


def _wrong_mark(pen, u, v, kind):
    """잘못된 표기 예시 — 옛 카드의 다섯 가지(V·X·점·세로줄·빗금)."""
    _bubble(pen, u, v, float(L.BUBBLE_W_MM) * 1.15,
            float(L.BUBBLE_H_MM) * 1.05, colour=INK)
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
    u0, v0, u1, v1 = box
    _rect(pen, u0, v0, u1, v1)
    header_v = v0 + 0.048
    _rect(pen, u0, v0, u1, header_v, fill=TINT, radius=1.0)
    _text(pen, (u0 + u1) / 2, (v0 + header_v) / 2, title, size=10.0, colour=GREEN, bold=True)
    _line(pen, u0, grid_v0 - 0.030, u1, grid_v0 - 0.030)


def _name_block(pen):
    _titled_grid_box(pen, BOX_NAME, "성    명    (좌측부터 차례로 마킹)",
                     float(L.NAME_ROW_V[0]))
    diameter = L.NAME_BUBBLE_D_MM
    for (col, row), (u, v) in L.name_cells().items():
        letters = L.VOWELS if col in L.NAME_VOWEL_COLUMNS else L.CONSONANTS
        _cell(pen, u, v, letters[row - 1], diameter, diameter, NAME_GLYPH_PT)


def _phone_block(pen):
    _titled_grid_box(pen, BOX_PHONE, "전화번호  끝  네  자리", float(L.PHONE_ROW_V[0]))
    for (_pos, digit), (u, v) in L.phone_cells().items():
        _cell(pen, u, v, str(digit))

    u0, v0, u1, v1 = BOX_PHONE_HOW
    _rect(pen, u0, v0, u1, v1, fill=TINT, radius=3.0)
    _text(pen, (u0 + u1) / 2, v0 + 0.023, PHONE_HOW_TITLE,
          size=10.4, colour=GREEN, bold=True)
    _line(pen, u0 + 0.018, v0 + 0.034, u1 - 0.018, v0 + 0.034, colour=GREEN, weight=1.0)
    v = v0 + 0.048
    step = (v1 - 0.010 - v) / (len(PHONE_HOW) - 1)
    for line, indent in PHONE_HOW:
        if line:
            start = u0 + (0.010, 0.021, 0.016, 0.030)[indent]
            _fitted(pen, start, v, line, 6.4, u1 - start - 0.008)
        v += step


def _divider(pen):
    u0, u1 = DIVIDER_U
    _rect(pen, u0, BOX_ANSWER_V[0], u1, BOX_ANSWER_V[1], fill=TINT, radius=2.0)


def _grid_column(pen, u0, header, rows_v, numbers, bottom=None):
    """답란·조사 공용 열 — 초록 문번칸 + 5줄마다 구분선(옛 카드 그대로).

    `bottom` 을 주면 그 높이에서 박스를 닫는다. 25문항처럼 **덜 찬 열**은
    끝까지 늘이지 않는다 — 수능 답안지도 45문항의 마지막 5문항 열은 짧다.
    빈 칸을 끝까지 그려 두면 학생이 아직 못 푼 문제가 있는 줄 안다.
    """
    box_w = float(L.mm_to_u(L.ANSWER_BOX_W_MM))
    u1 = u0 + box_w
    top, full_bottom = BOX_ANSWER_V
    bottom = full_bottom if bottom is None else bottom
    header_v = top + 0.040
    number_u = u0 + NUMBER_COL_U

    _rect(pen, u0, top, u1, bottom)
    _rect(pen, u0, top, number_u, bottom, fill=TINT, radius=1.0)
    _rect(pen, u0, top, u1, header_v, fill=TINT, radius=1.0)
    _text(pen, (u0 + number_u) / 2, (top + header_v) / 2, "문번", size=8.6, colour=GREEN, bold=True)
    _text(pen, (number_u + u1) / 2, (top + header_v) / 2, header, size=9.4, colour=GREEN, bold=True)
    _line(pen, u0, header_v, u1, header_v)
    _line(pen, number_u, top, number_u, bottom)

    for index, v in enumerate(rows_v):
        if v > bottom:
            break
        label = numbers.get(index)
        if label is not None:
            _text(pen, (u0 + number_u) / 2, v, str(label),
                  size=10.0, colour=GREEN, bold=True)
        if index and index % GROUP_EVERY == 0:
            gap = (rows_v[index] - rows_v[index - 1]) / 2
            _line(pen, u0, v - gap, u1, v - gap, colour=GREEN, weight=1.2)
    return u1


def _answer_block(pen, card):
    """답란 — 20행이 차면 다음 열(수능 방식). 열 1은 옛 카드와 같은 자리다."""
    cells = card.answer_cells()
    pitch = float(L.mm_to_u(L.ANSWER_COL_PITCH_MM))
    first_u = float(L.mm_to_u(L.ANSWER_COL_X_MM)) - 0.041
    step_v = float(L.mm_to_v(L.ROW_PITCH_MM))
    per = L.ANSWER_ROWS_PER_COL
    for col in range(card.columns):
        questions = sorted(q for q in cells if (q - 1) // per == col)
        rows_v = [cells[q][0][1] for q in questions]
        # 덜 찬 열은 마지막 문항 바로 아래에서 닫는다.
        short = None if len(questions) == per else rows_v[-1] + step_v * 0.62
        _grid_column(pen, first_u + col * pitch, "답    란", rows_v,
                     dict(enumerate(questions)), bottom=short)
    for choices in cells.values():
        for index, (u, v) in enumerate(choices, start=1):
            _cell(pen, u, v, str(index))


def _survey_block(pen, card):
    """성적 조사 — 왼쪽은 답안 카드와 똑같고 오른쪽만 다르다(대표 2026-08-18).

    점수는 **한 열**이다. 십의 자리가 위(1~5), 일의 자리가 아래(1~9,0) —
    원본 조사 카드가 그렇다. 두 열로 갈라 놓았던 것을 되돌렸다.
    """
    pitch = float(L.mm_to_u(L.ANSWER_COL_PITCH_MM))
    first_u = float(L.mm_to_u(L.ANSWER_COL_X_MM)) - 0.041
    step_v = float(L.mm_to_v(L.ROW_PITCH_MM))
    first_v = float(L.mm_to_v(L.ANSWER_FIRST_ROW_MM))
    rows_v = [first_v + row * step_v for row in range(L.ANSWER_ROWS_PER_COL)]

    labels = {L.SURVEY_TENS_ROW0: "십", L.SURVEY_ONES_ROW0: "일"}
    _grid_column(pen, first_u, "점    수", rows_v, labels)
    for (_place, digit), (u, v) in card.survey_cells().items():
        _cell(pen, u, v, digit)

    _survey_side(pen, first_u + pitch)


def _survey_side(pen, bu0):
    """★내 점수★ 손글씨 칸 + 마킹방법. 94장 중 34장이 버블 대신 여기에 적었다."""
    box_w = float(L.mm_to_u(L.ANSWER_BOX_W_MM))
    bu1 = bu0 + box_w
    top, bottom = BOX_ANSWER_V
    header_v = top + 0.040
    hand_bottom = top + 0.300

    _rect(pen, bu0, top, bu1, hand_bottom)
    _rect(pen, bu0, top, bu1, header_v, fill=TINT, radius=1.0)
    _text(pen, (bu0 + bu1) / 2, (top + header_v) / 2, "★  내 점수  ★",
          size=9.4, colour=GREEN, bold=True)

    line_step = 0.022
    how_v0 = hand_bottom + 0.034
    how_v1 = how_v0 + 0.070 + len(SURVEY_HOW) * line_step + 0.070
    _rect(pen, bu0, how_v0, bu1, how_v1, fill=TINT, radius=3.0)
    _text(pen, (bu0 + bu1) / 2, how_v0 + 0.026, SURVEY_HOW_TITLE,
          size=10.4, colour=GREEN, bold=True)
    _line(pen, bu0 + 0.018, how_v0 + 0.038, bu1 - 0.018, how_v0 + 0.038,
          colour=GREEN, weight=1.0)

    v = how_v0 + 0.062
    for line, indent in SURVEY_HOW:
        if line:
            start_u = bu0 + (0.012, 0.024, 0.018)[indent]
            _fitted(pen, start_u, v, line, 6.4, bu1 - start_u - 0.010)
        v += line_step

    gap = float(L.mm_to_u(L.CHOICE_PITCH_MM)) * 2.4
    v += 0.028
    _text(pen, bu0 + 0.014, v, "예시)  43점", size=7.0, anchor="left", bold=True)
    first = bu1 - 0.022 - gap
    for column, (label, digit) in enumerate((("십", "4"), ("일", "3"))):
        u = first + column * gap
        # 숫자를 칠해진 칸 **안**에 흰 글자로 넣으면 안 보인다 — 6pt 획이
        # 검은 바탕에 묻힌다. 칸 밖에 두면 어느 칸을 칠했는지가 그대로 읽힌다.
        _text(pen, u, v - 0.028, label, size=6.6, colour=GREEN, bold=True)
        _filled_bubble(pen, u, v)
        _text(pen, u, v + 0.030, digit, size=7.0, bold=True)


def render(card, title="한종철 생명과학", exam=""):
    """카드 한 장을 PDF 바이트로.

    `card` 는 `layout.Layout`, `exam` 은 회차명(`2027 OMEGA black 3회`).
    """
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
    _header(pen, title, exam)
    _school_block(pen)
    _rules_block(pen)
    _name_block(pen)
    _phone_block(pen)
    _divider(pen)
    if card.is_survey:
        _survey_block(pen, card)
    else:
        _answer_block(pen, card)

    _text(pen, 0.992, HEAD_EXAM_V, card.name, size=9.0, anchor="right", colour=GREEN, bold=True)

    pen.showPage()
    pen.save()
    return buffer.getvalue()

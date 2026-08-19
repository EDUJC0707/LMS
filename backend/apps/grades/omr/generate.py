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
from decimal import Decimal

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
#: 약점 체크 열의 머리칸 — 연한 살구(대표 2026-08-19). 답을 적는 자리와 "더 받고
#: 싶다"를 말하는 자리는 하는 일이 다르니 색으로도 갈라 준다.
#:
#: 초록 머리칸(#C3E9C2)과 **밝기를 맞췄다**(220 대 217) — 나란히 놓아도 한쪽이
#: 먼저 눈에 들어오지 않는다. 인쇄를 직접 하므로 색 하나 더 쓰는 데 비용이 없다.
EXTRA_TINT = Color(0xFA / 255, 0xD6 / 255, 0xAA / 255)
INK = Color(0x23 / 255, 0x1F / 255, 0x20 / 255)

#: 버블 안 글자 — 옛 카드에서 링 높이의 약 40% 다. 작게 그렸더니 원본보다
#: 눈에 띄게 작았다(대표 지적). 리더 입장에서도 **원본과 같은 크기가 안전하다**:
#: 상대화 문턱이 이 글리프가 인쇄된 지면에서 맞춰졌다.
#: 답란·전화는 글리프가 링 높이의 84% 다(원본 실측 1.78x3.94mm / 2.54x4.70mm).
#: 지금 값이 82~83% 로 이미 맞는다.
CELL_GLYPH_PT = 7.3
#: 성명은 다르다 — 원본이 링 3.62x3.94mm 에 글리프 1.52x2.03mm 로 **52%** 다.
#: 6.0pt 로 그렸더니 69% 라 칸을 꽉 채워 답란보다 크게 보였다.
NAME_GLYPH_PT = 6.4

#: 박스 자리 — 옛 카드 200dpi 렌더에서 잰 정규좌표 그대로.
BOX_SCHOOL = (0.025, 0.210, 0.272, 0.310)
BOX_NAME = (0.025, 0.326, 0.273, 0.967)
#: 가로 간격은 **하나로 푼다**. 신원란 끝(0.273)과 답란 시작(0.4796)은 고정이고
#: 그 사이에 안내 박스와 구분바가 들어간다 — 남는 자리를 셋으로 나누면
#: 6.27mm 가 나온다. 눈으로 맞추던 때는 5.93 / 7.91 / 4.96mm 로 벌어져 있었다.
COLUMN_GAP = 0.02219
BOX_RULES = (0.2952, 0.069, 0.4212, 0.312)
BOX_PHONE = (0.2952, 0.329, 0.4212, 0.812)
BOX_PHONE_HOW = (0.2952, 0.823, 0.4212, 0.967)
DIVIDER_U = (0.4434, 0.4574)

#: 답란 1번 위와 20번 아래의 여백을 **같게** 둔다(대표 2026-08-19). 행 자리는
#: 옛 카드에서 물려받아 고정이므로, 머리칸 아래와 박스 아래를 행에서 역산한다.
#: 예전에는 위 7.61mm 아래 8.35mm 로 0.7mm 어긋나 있었다. 맞춘 뒤 버블
#: 끝에서 잰 여백이 5.87mm 라 20% 줄였다(대표 2026-08-19) -> 4.70mm.
ANSWER_ROW_MARGIN_MM = 6.81
_ROW1_V = float(L.mm_to_v(L.ANSWER_FIRST_ROW_MM))
_ROW_LAST_V = float(L.mm_to_v(L.ANSWER_FIRST_ROW_MM + 19 * L.ROW_PITCH_MM))
_ROW_MARGIN_V = float(L.mm_to_v(Decimal(str(ANSWER_ROW_MARGIN_MM))))
ANSWER_HEADER_V = _ROW1_V - _ROW_MARGIN_V
BOX_ANSWER_V = (0.022, _ROW_LAST_V + _ROW_MARGIN_V)

#: 머리말 자리 — 옛 카드 실측(지면 왼쪽 끝 기준 제목 14.4mm, 로고 22.5mm).
#: 눈으로 맞추던 때는 둘 다 11.4mm 에 붙어 있어 제목이 3mm, 로고가 11mm
#: 왼쪽으로 밀려 있었다.
HEAD_EXAM_V = 0.030
HEAD_U = 0.0256
#: 로고는 제목보다 더 안으로 들어간다.
LOGO_U = 0.0613
LOGO_V = 0.1199
#: 제목 크기 — 원본은 12.6pt 상당이지만 **더 크게 간다**(대표 2026-08-19).
HEAD_EXAM_PT = 18.5

#: 안내 문구 — **원본 줄폭에서 역산한 값**이다. 옛 카드의 줄 하나하나를 재
#: 폭을 얻고, 같은 문구가 그 폭이 되는 크기를 구했다. 블록 안에서는 값이
#: 5.94~5.99pt 로 모여 있었다 — 원본은 크기가 안 튄다.
RULES_PT = 6.0
#: ※ 줄만 작다. 원본이 4.97pt 로 일부러 낮춰 놓았다.
RULES_NOTE_PT = 5.0
PHONE_PT = 5.4
#: 조사 카드의 설명문 — 원본은 글자가 열 폭을 꽉 채운다(3.30~3.64mm).
SURVEY_NOTE_PT = 7.4

#: 들여쓰기·여백도 원본 실측이다(박스 안쪽 왼쪽 끝 기준 mm).
#: 예전 값은 1단 3.4mm·2단 7.3mm 로 원본의 2.4배였고, 그래서 글자가 들어갈
#: 자리가 없어 축소가 걸렸다. 원인은 글자 크기가 아니라 **여백**이었다.
RULES_INDENT_MM = (1.40, 3.81, 3.05, 0.0)
PHONE_INDENT_MM = (0.89, 2.54, 2.54, 7.75)
TEXT_RIGHT_MM = 1.1

#: 5문항마다 구분선 — 옛 카드에 있다. 20줄이 한 덩어리면 줄을 잘못 탄다.
GROUP_EVERY = 5

#: 박스 모서리 반경 — **전부 같은 값**을 쓴다(대표 2026-08-19). 자리마다
#: 1.0/2.0/3.0 으로 달랐더니 같은 지면에서 모서리가 제각각으로 보였다.
RADIUS = 2.0

#: 굵게 — 겹쳐 찍을 때 밀어 주는 거리(글자 크기 대비).
BOLD_STROKE = 0.022

#: 세로 배치 — 본문이 34.6mm 인데 박스 안 높이가 46.1mm 다. 예전에는 본문을
#: 11.8mm 에서 시작해 마지막 줄이 박스 **밖으로** 나갔다(48.5mm). 제목·밑줄을
#: 위로 붙이고 본문을 8.5mm 에서 시작하면 45.2mm 로 들어간다.
#: 제목 위 여백 — 원래 0.024(4.55mm)를 절반으로 줄였더니 2.28mm 라 제목 글자
#: (약 3mm)가 테두리에 닿았다. 그 중간인 3.6mm 로 둔다. 아래 내용은 같은 만큼
#: 따라 올라간다 — **박스 크기는 그대로다.**
RULES_TITLE_V = 0.019
RULES_RULE_V = 0.029
RULES_BODY_V = 0.040

RULES_TITLE = "지켜야 할 사항"
#: (문구, 들여쓰기 단, **다음 줄까지의 간격 mm**). 간격을 균등하게 두면 항목이
#: 한 덩어리로 붙어 버린다 — 원본은 항목 안이 3.6mm, 항목 사이가 4.1~4.6mm,
#: 예시 버블 다음이 7.6mm 로 리듬이 있다(옛 카드 실측).
RULES = [
    ("1. 반드시 검정색 싸인펜으로 표기", 0, 3.6),
    ("합니다.", 1, 3.8),
    ("※ 샤프펜슬, 볼펜 사용시 불이익 발생", 2, 4.1),
    ("2. 표기란에는", 0, 4.6),   # 뒤에 버블이 붙고 이어서 아래 조각이 온다
    ("표기해야 합니다.", 1, 3.7),
    ("(잘못된 표기 예시)", 3, 3.6),
]
#: 잘못된 표기 예시 — 원본 실측: 왼쪽 8.0mm 에서 시작, 칸 간격 4.1mm,
#: 칸 크기 3.0 x 5.4mm(본 버블보다 크다).
WRONG_START_MM = 8.0
WRONG_PITCH_MM = 4.1
WRONG_W_MM = 3.0
WRONG_H_MM = 5.4
WRONG_ADVANCE_MM = 7.6
RULES_TAIL = [("3. 수정시에는 수정테이프만을", 0, 3.6), ("사용하여 깨끗하게 수정합니다.", 1, 0.0)]
#: 2번 줄은 **버블을 사이에 끼워** 그린다 — 글자·버블·글자 세 조각.
#: 공백을 넣고 그 폭을 재서 얹던 방식은 간격이 원본과 어긋났다.
RULE_MARK_TAIL = "와 같이 바르게"

#: 원본 조사 카드 문구 그대로(2026-06-12 실물). 화살표가 어느 덩어리를
#: 가리키는지까지 원본이 정해 놓았다 — 위 덩어리는 십의 자리, 아래는 일의 자리.
SURVEY_TENS_NOTE = ["점수의 10의 자리 숫", "자에 마킹", "(42점이면 4에 마킹)"]
SURVEY_ONES_NOTE = ["점수의 1의 자리 숫", "자에 마킹", "(42점이면 2에 마킹)"]
MYSCORE_NOTE = ["마킹 제대로 되었는지 확인용입니다.", "꼭 작성해주세요 :) 수고했습니다."]
#: 세 가지 예시 — 08점이 0 의 자리를 가르친다(십의 자리를 안 칠한다).
SURVEY_EXAMPLES = ((8, "08점"), (42, "42점"), (35, "35점"))

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
    # 굵게는 **같은 글자를 살짝 밀어 두 번** 찍는다. 예전에는 PDF 렌더 모드
    # 2(채우고 두르기)를 썼는데, `Tr` 은 한 번 켜지면 그래프 상태에 남고
    # reportlab 은 "이미 0 이겠지" 하고 `0 Tr` 을 안 쓴다 — 실제 PDF 에 `2 Tr`
    # 47개, `0 Tr` 0개였다. 그래서 볼드 뒤에 오는 글자가 전부 볼드로 남았고,
    # 3번 항목만 굵어 보인 것도 이것이었다. 겹쳐 찍기는 상태를 안 남긴다.
    # 대각으로 조금 민다. 가로로만 밀면 확대했을 때 글자가 겹쳐 보인다
    # ("전화번호 끝끝 네네 자리자리" 로 읽혔다).
    passes = ((0.0, 0.0), (size * BOLD_STROKE, size * BOLD_STROKE)) if bold else ((0.0, 0.0),)
    for chunk, is_latin in _runs(body):
        face = _face(is_latin, bold)
        for dx, dy in passes:
            text = pen.beginText(x + dx, y + dy)
            text.setFont(face, size)
            text.setFillColor(fill)
            text.textOut(chunk)
            pen.drawText(text)
        x += pdfmetrics.stringWidth(chunk, face, size)
    pen.setFillColor(INK)


def overflow(body, size, room_u, bold=False):
    """이 줄이 박스 폭을 넘는 mm. 0 이하면 들어간다.

    **줄마다 글자를 줄이지 않는다.** 예전에는 넘치면 그 줄만 축소했는데, 그 결과
    긴 줄은 작고 짧은 줄은 커져 한 문단 안에서 크기가 계단처럼 튀었다(실측:
    5.7 / 7.2 / 4.7 / 6.3 / 5.3pt). 원본은 크기가 고정이고 줄을 나눌 뿐이다.
    안 들어가면 **문구를 나누거나 박스를 넓히는 것이 답**이고, 그건 사람이 정한다 —
    테스트가 넘침을 잡는다.
    """
    room_pt = room_u * float(L.SPAN_X_MM) * MM_UNIT
    return (_width(body, size, bold) - room_pt) / MM_UNIT


# --- 도형 ------------------------------------------------------------------


def _stroke():
    return float(L.STROKE_MM) * MM_UNIT


def _down(mm):
    """mm 만큼 아래로 — 줄 간격을 실측 mm 로 적기 위한 변환."""
    return float(L.mm_to_v(Decimal(str(mm))))


def _xy(u, v):
    x_mm, y_mm = L.to_mm(u, v)
    return float(x_mm) * MM_UNIT, float(y_mm) * MM_UNIT


#: 어느 모서리를 둥글릴지. 붙어 있는 칸은 **바깥쪽만** 둥글어야 한다 —
#: 문번 머리칸의 아래 모서리가 둥글면 밑으로 이어지는 칸이 거기서 끊겨 보인다.
ALL_CORNERS = (True, True, True, True)      # 좌상, 우상, 우하, 좌하
TOP_ONLY = (True, True, False, False)
LEFT_ONLY = (True, False, False, True)
TOP_LEFT_ONLY = (True, False, False, False)
NO_CORNERS = (False, False, False, False)


def _rect(pen, u0, v0, u1, v1, fill=None, radius=None, edge=None, corners=None,
          stroke=True):
    """모서리를 골라 둥글리는 사각형.

    `corners` 는 (좌상, 우상, 우하, 좌하). 넷 다 둥근 것이 기본이지만, 다른 칸에
    붙는 변은 각지게 둬야 이어져 보인다.
    """
    x0, y0 = _xy(u0, v0)
    x1, y1 = _xy(u1, v1)
    r = RADIUS if radius is None else radius
    top, bottom = max(y0, y1), min(y0, y1)
    tl, tr, br, bl = corners or ALL_CORNERS
    path = pen.beginPath()
    path.moveTo(x0 + (r if tl else 0), top)
    path.lineTo(x1 - (r if tr else 0), top)
    if tr:
        path.curveTo(x1, top, x1, top, x1, top - r)
    path.lineTo(x1, bottom + (r if br else 0))
    if br:
        path.curveTo(x1, bottom, x1, bottom, x1 - r, bottom)
    path.lineTo(x0 + (r if bl else 0), bottom)
    if bl:
        path.curveTo(x0, bottom, x0, bottom, x0, bottom + r)
    path.lineTo(x0, top - (r if tl else 0))
    if tl:
        path.curveTo(x0, top, x0, top, x0 + r, top)
    path.close()
    pen.setStrokeColor(edge or INK)
    pen.setLineWidth(_stroke() * 2.2)
    if fill is not None:
        pen.setFillColor(fill)
    pen.drawPath(path, stroke=1 if stroke else 0, fill=1 if fill is not None else 0)
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
    """버블 한 칸 — **링도 글자도 분홍**이다(원본 그대로).

    칸 안에 있는 것은 전부 분홍, 칸 밖의 라벨·머리글·문번은 검정이다. 검정
    사인펜 마킹과 인쇄물이 같은 색이면 사람도 기계도 가르기 어렵다 — 그래서
    학생이 칠할 자리는 통째로 분홍으로 둔다.
    """
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
    """네 귀퉁이 마커 — **위가 아래보다 크다.**

    리더가 방향을 그걸로 정한다. 넷을 같게 그리면 카드가 어느 쪽이 위인지
    알 수 없어 전부 보류된다.
    """
    pen.setFillColor(black)
    w = float(L.MARK_W_MM) * MM_UNIT
    for v, height_mm in ((0.0, L.MARK_TOP_H_MM), (1.0, L.MARK_BOTTOM_H_MM)):
        h = float(height_mm) * MM_UNIT
        for u in (0.0, 1.0):
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


#: 회차명이 들어갈 수 있는 최대 폭(마커 기준 mm). 제목은 안내 박스보다 **위**라
#: 그쪽과는 안 부딪힌다. 먼저 만나는 것은 **세로 구분바**다 — 답란 열까지 있다고
#: 계산했다가 구분바를 뚫고 나갔다. 앞에 3mm 를 비워 둔다.
HEAD_ROOM_MM = (DIVIDER_U[0] - HEAD_U) * float(L.SPAN_X_MM) - 3.0
#: 여기까지는 줄여서 넣는다. 그 밑으로는 읽으라고 찍는 글자가 아니다.
HEAD_MIN_PT = 9.0


def _exam_size(exam):
    """회차명이 자리에 들어가는 크기. 안 되면 이름을 줄이라고 말한다.

    제목은 **한 줄뿐**이라 줄여도 다른 줄과 크기가 어긋날 일이 없다(안내 문구를
    줄마다 줄이던 것과는 다른 얘기다). 다만 끝없이 줄이지는 않는다 — 9pt 밑으로
    가야 들어가는 이름이면 지면이 아니라 이름이 문제다. 잘라 내거나 깨알같이
    찍어 내보내느니 여기서 막는다.
    """
    width = _width(exam, HEAD_EXAM_PT) / MM_UNIT
    if width <= HEAD_ROOM_MM:
        return HEAD_EXAM_PT
    fitted = HEAD_EXAM_PT * HEAD_ROOM_MM / width
    if fitted < HEAD_MIN_PT:
        raise ValueError(
            f"회차명이 너무 깁니다({width:.0f}mm, 자리는 {HEAD_ROOM_MM:.0f}mm): "
            f"{exam!r} — 짧게 적어 주세요"
        )
    return fitted


def _header(pen, title, exam):
    """회차명 + 로고. 회차는 시험을 만들 때 채운다(대표 2026-08-18).

    비우면 손으로 적을 줄을 남긴다 — 미리 찍어 둘 수도 있어야 한다.
    """
    if exam:
        _text(pen, HEAD_U, HEAD_EXAM_V, exam, size=_exam_size(exam), anchor="left")
    else:
        _line(pen, HEAD_U, HEAD_EXAM_V + 0.012, HEAD_U + 0.185,
              HEAD_EXAM_V + 0.012, weight=1.0)
        _text(pen, HEAD_U + 0.193, HEAD_EXAM_V, "회차", size=6.5, anchor="left")

    if LOGO.exists():
        art = ImageReader(str(LOGO))
        width_px, height_px = art.getSize()
        width_mm = 33.0   # 원본 실측 폭. 크게 그렸더니 지면을 잡아먹었다
        height_mm = width_mm * height_px / width_px
        x, y = _xy(LOGO_U, LOGO_V)
        pen.drawImage(art, x, y - height_mm * MM_UNIT / 2,
                      width=width_mm * MM_UNIT, height=height_mm * MM_UNIT,
                      mask="auto")
    else:
        _text(pen, LOGO_U, LOGO_V, title, size=13, anchor="left")


def _school_block(pen):
    """학교 / 학급 — 옛 카드의 `학원` 자리가 학급이다(대표 2026-08-18)."""
    u0, v0, u1, v1 = BOX_SCHOOL
    label_u = u0 + (u1 - u0) * 0.235
    mid_v = (v0 + v1) / 2
    _rect(pen, u0, v0, u1, v1)
    for top, bottom, label in ((v0, mid_v, "학 교"), (mid_v, v1, "학 급")):
        _rect(pen, u0, top, label_u, bottom, fill=TINT,
              corners=TOP_LEFT_ONLY if top == v0 else (False, False, False, True))
        _text(pen, (u0 + label_u) / 2, (top + bottom) / 2, label, size=11.0, bold=True)
    _line(pen, label_u, mid_v, u1, mid_v)
    _text(pen, u1 - 0.008, (v0 + mid_v) / 2, "고등학교", size=10.5, anchor="right", bold=True)


def _rules_block(pen):
    u0, v0, u1, v1 = BOX_RULES
    _rect(pen, u0, v0, u1, v1, fill=TINT)
    centre = (u0 + u1) / 2
    _text(pen, centre, v0 + RULES_TITLE_V, RULES_TITLE, size=8.2, bold=True)
    _line(pen, u0 + 0.026, v0 + RULES_RULE_V, u1 - 0.026, v0 + RULES_RULE_V, weight=1.0)

    indents = tuple(float(L.mm_to_u(Decimal(str(x)))) for x in RULES_INDENT_MM)
    v = v0 + RULES_BODY_V
    for line, indent, advance in RULES:
        if indent == 3:
            _text(pen, centre, v, line, size=RULES_PT, anchor="middle", bold=True)
        elif line.startswith("2. 표기란에는"):
            _inline_mark(pen, u0 + indents[indent], v, line)
        else:
            _text(pen, u0 + indents[indent], v, line,
                  size=RULES_NOTE_PT if indent == 2 else RULES_PT, anchor="left", bold=True)
        v += _down(advance)

    start_u = u0 + float(L.mm_to_u(Decimal(str(WRONG_START_MM))))
    pitch_u = float(L.mm_to_u(Decimal(str(WRONG_PITCH_MM))))
    for index in range(5):
        _wrong_mark(pen, start_u + index * pitch_u, v + _down(WRONG_H_MM / 2), index)
    v += _down(WRONG_ADVANCE_MM)
    for line, indent, advance in RULES_TAIL:
        _text(pen, u0 + indents[indent], v, line, size=RULES_PT, anchor="left",
              bold=True)
        v += _down(advance)


def _inline_mark(pen, u, v, head):
    """`2. 표기란에는 ● 와 같이 바르게` — 글자·버블·글자를 이어 그린다.

    한 문자열에 공백을 박고 폭을 재서 버블을 얹으면 자간이 원본과 안 맞는다.
    조각을 차례로 놓으면 앞뒤 여백을 mm 로 정확히 줄 수 있다.
    """
    pad = float(L.mm_to_u(Decimal("1.6")))
    _text(pen, u, v, head, size=RULES_PT, anchor="left", bold=True)
    after = u + float(L.mm_to_u(Decimal(str(_width(head, RULES_PT) / MM_UNIT))))
    bubble_u = after + pad + float(L.BUBBLE_RU)
    _filled_bubble(pen, bubble_u, v)
    _text(pen, bubble_u + float(L.BUBBLE_RU) + pad, v, RULE_MARK_TAIL,
          size=RULES_PT, anchor="left", bold=True)


def _wrong_mark(pen, u, v, kind):
    """잘못된 표기 예시 — 옛 카드의 다섯 가지(V·X·점·세로줄·빗금)."""
    _bubble(pen, u, v, WRONG_W_MM, WRONG_H_MM, colour=INK)
    x, y = _xy(u, v)
    w = WRONG_W_MM * MM_UNIT / 2
    h = WRONG_H_MM * MM_UNIT / 2
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


def _titled_grid_box(pen, box, title, grid_v0, cells=4, columns=()):
    """성명·전화 공용 — 제목칸 + 손으로 쓰는 줄 + 그 줄을 가르는 초록 점선.

    옛 카드는 손글씨 줄을 **점선으로 칸을 나눠** 둔다(성명 4글자·전화 4자리).
    한 칸에 한 글자씩 적게 만드는 장치라 마킹 열과 눈으로 이어진다.
    """
    u0, v0, u1, v1 = box
    _rect(pen, u0, v0, u1, v1)
    header_v = v0 + 0.048
    _rect(pen, u0, v0, u1, header_v, fill=TINT, corners=TOP_ONLY)
    _text(pen, (u0 + u1) / 2, (v0 + header_v) / 2, title, size=10.0, bold=True)
    write_v = grid_v0 - 0.030
    # 답란 안 5줄 구분선과 같은 두께로 — 굵으면 손글씨 칸이 도드라진다.
    _line(pen, u0, write_v, u1, write_v, colour=GREEN, weight=1.2)
    for edge in _divider_us(u0, u1, cells, columns):
        _dashed(pen, edge, header_v, edge, v1)


def _divider_us(u0, u1, cells, columns):
    """칸막이 x — 마킹 열이 있으면 **열 사이 한가운데**, 없으면 균등 분할."""
    if columns:
        per = len(columns) // cells
        return [
            (float(columns[index * per - 1]) + float(columns[index * per])) / 2
            for index in range(1, cells)
        ]
    return [u0 + (u1 - u0) * index / cells for index in range(1, cells)]


def _dashed(pen, u0, v0, u1, v1):
    x0, y0 = _xy(u0, v0)
    x1, y1 = _xy(u1, v1)
    pen.setStrokeColor(GREEN)
    pen.setLineWidth(_stroke())
    pen.setDash(3, 3)
    pen.line(x0, y0, x1, y1)
    pen.setDash()
    pen.setStrokeColor(INK)


def _name_block(pen):
    _titled_grid_box(pen, BOX_NAME, "성    명    (좌측부터 차례로 마킹)",
                     float(L.NAME_ROW_V[0]), cells=4, columns=L.NAME_COL_U)
    for (col, row), (u, v) in L.name_cells().items():
        letters = L.VOWELS if col in L.NAME_VOWEL_COLUMNS else L.CONSONANTS
        _cell(pen, u, v, letters[row - 1],
              L.NAME_BUBBLE_W_MM, L.NAME_BUBBLE_H_MM, NAME_GLYPH_PT)


def _phone_block(pen):
    _titled_grid_box(pen, BOX_PHONE, "전화번호  뒤  4자리",
                     float(L.PHONE_ROW_V[0]), cells=L.PHONE_CELLS)
    for (_pos, digit), (u, v) in L.phone_cells().items():
        _cell(pen, u, v, str(digit))

    u0, v0, u1, v1 = BOX_PHONE_HOW
    _rect(pen, u0, v0, u1, v1, fill=TINT)
    _text(pen, (u0 + u1) / 2, v0 + 0.018, PHONE_HOW_TITLE, size=7.8, bold=True)
    _line(pen, u0 + 0.018, v0 + 0.029, u1 - 0.018, v0 + 0.029, weight=1.0)
    v = v0 + 0.043
    step = (v1 - 0.010 - v) / (len(PHONE_HOW) - 1)
    for line, indent in PHONE_HOW:
        if line:
            start = u0 + float(L.mm_to_u(Decimal(str(PHONE_INDENT_MM[indent]))))
            _text(pen, start, v, line, size=PHONE_PT, anchor="left", bold=True)
        v += step


def _divider(pen):
    u0, u1 = DIVIDER_U
    _rect(pen, u0, BOX_ANSWER_V[0], u1, BOX_ANSWER_V[1], fill=TINT)


#: 추가 마킹란 머리글(대표 2026-08-19). 칸을 14.5mm 로 넓혀 **한 줄**로 앉는다.
#:
#: 이 칸이 실제로 물리는 곳이 약점체크다 — `약점체크 = 오답 OR 추가마킹`
#: (`SheetAnswer.extra_practice_marked`). 맞은 문제에 체크해도 들어간다.
EXTRA_HEADER = "약점 체크"


def _grid_column(pen, u0, header, rows_v, numbers, bottom=None, extra=False):
    """답란·조사 공용 열 — 초록 문번칸 + 5줄마다 구분선(옛 카드 그대로).

    `bottom` 을 주면 그 높이에서 박스를 닫는다. 25문항처럼 **덜 찬 열**은
    끝까지 늘이지 않는다 — 수능 답안지도 45문항의 마지막 5문항 열은 짧다.
    빈 칸을 끝까지 그려 두면 학생이 아직 못 푼 문제가 있는 줄 안다.
    """
    number_w = float(L.mm_to_u(L.NUMBER_COL_W_MM))
    u1 = u0 + float(L.mm_to_u(L.ANSWER_BOX_W_MM))
    top, full_bottom = BOX_ANSWER_V
    bottom = full_bottom if bottom is None else bottom
    header_v = ANSWER_HEADER_V
    number_u = u0 + number_w

    _rect(pen, u0, top, u1, bottom)
    # 문번 칸은 위·아래가 박스 테두리에 닿는다 — 왼쪽 두 모서리만 둥글다.
    _rect(pen, u0, top, number_u, bottom, fill=TINT, corners=LEFT_ONLY)
    _rect(pen, u0, top, u1, header_v, fill=TINT, corners=TOP_ONLY)
    _text(pen, (u0 + number_u) / 2, (top + header_v) / 2, "문번", size=8.6, bold=True)
    _text(pen, (number_u + u1) / 2, (top + header_v) / 2, header, size=9.4, bold=True)
    _line(pen, u0, header_v, u1, header_v)
    _line(pen, number_u, top, number_u, bottom)
    if extra:
        _extra_column(pen, u1 + float(L.mm_to_u(L.EXTRA_SEP_MM)), top, bottom, header_v)

    for index, v in enumerate(rows_v):
        if v > bottom:
            break
        label = numbers.get(index)
        if label is not None:
            # 5 의 배수만 굵게 — 옛 카드가 그렇다. 스무 줄이 전부 같은 무게면
            # 눈이 짚을 자리가 없어 학생이 줄을 잘못 탄다.
            heavy = isinstance(label, int) and label % GROUP_EVERY == 0
            _text(pen, (u0 + number_u) / 2, v, str(label),
                  size=11.7 if heavy else 10.6, bold=heavy)
        if index and index % GROUP_EVERY == 0:
            gap = (rows_v[index] - rows_v[index - 1]) / 2
            _line(pen, u0, v - gap, u1, v - gap, colour=GREEN, weight=1.2)
    return u1


def _extra_column(pen, u0, top, bottom, header_v):
    """약점 체크 — 답란과 **떨어져 선 열**. 머리칸만 분홍 색조로 갈라 준다."""
    u1 = u0 + float(L.mm_to_u(L.EXTRA_COL_W_MM))
    _rect(pen, u0, top, u1, bottom)
    _rect(pen, u0, top, u1, header_v, fill=EXTRA_TINT, corners=TOP_ONLY)
    _text(pen, (u0 + u1) / 2, (top + header_v) / 2, EXTRA_HEADER, size=8.6, bold=True)
    _line(pen, u0, header_v, u1, header_v)


def _answer_block(pen, card):
    """답란 — 20행이 차면 다음 열(수능 방식). 열 1은 옛 카드와 같은 자리다."""
    cells = card.answer_cells()
    pitch = float(L.mm_to_u(L.ANSWER_COL_PITCH_MM))
    first_u = float(L.mm_to_u(L.ANSWER_COL_LEFT_MM))
    step_v = float(L.mm_to_v(L.ROW_PITCH_MM))
    per = L.ANSWER_ROWS_PER_COL
    for col in range(card.columns):
        questions = sorted(q for q in cells if (q - 1) // per == col)
        rows_v = [cells[q][0][1] for q in questions]
        # 덜 찬 열은 **1열의 5줄 구분선과 같은 높이**에서 닫는다. 0.62 로 두었을
        # 때 25번 박스 하단이 5번 구분선보다 0.98mm 아래로 내려가 어긋나 보였다.
        short = None if len(questions) == per else rows_v[-1] + step_v * 0.5
        _grid_column(pen, first_u + col * pitch, "답    란", rows_v,
                     dict(enumerate(questions)), bottom=short, extra=True)
    for choices in cells.values():
        for index, (u, v) in enumerate(choices, start=1):
            _cell(pen, u, v, str(index))
    # 추가 마킹란은 **빈 칸**이다 — 안에 숫자를 넣으면 답란처럼 보인다.
    for u, v in card.extra_cells().values():
        _bubble(pen, u, v, L.BUBBLE_W_MM, L.BUBBLE_H_MM)


def _survey_block(pen, card):
    """성적 조사 — 왼쪽은 답안 카드와 같고 오른쪽은 **원본 조사 카드**를 따른다.

    원본은 점수를 "버블 안에 숫자"로 적지 않는다. 문번 칸에 **숫자**가 있고
    답란에는 **빈 칸 하나**뿐이다 — 자기 점수의 자릿수와 같은 줄을 칠한다.
    두 덩어리(십·일) 사이에 설명이 들어가고 화살표가 어느 쪽인지 가리킨다.
    """
    pitch = float(L.mm_to_u(L.ANSWER_COL_PITCH_MM))
    first_u = float(L.mm_to_u(L.ANSWER_COL_LEFT_MM))
    _score_column(pen, first_u, card)
    _survey_side(pen, first_u + pitch, card)


def _score_column(pen, u0, card):
    """점수 열 — 문번이 숫자, 답란은 칸 하나. 사이에 설명과 화살표.

    **설명이 놓이는 구간에는 문번 칸도 세로 구분선도 없다**(원본 그대로).
    끝까지 그었더니 세로줄이 `점수의|10의 자리 숫` 처럼 글자를 잘랐고 초록
    바탕까지 글자 밑에 깔려 읽기가 제일 나빴다.
    """
    box_w = float(L.mm_to_u(L.ANSWER_BOX_W_MM))
    u1 = u0 + box_w
    top, bottom = BOX_ANSWER_V
    header_v = ANSWER_HEADER_V
    number_u = u0 + float(L.mm_to_u(L.NUMBER_COL_W_MM))
    cells = card.survey_cells()
    half = float(L.mm_to_v(L.ROW_PITCH_MM)) / 2

    tens_last = max(v for (place, _), (_, v) in cells.items() if place == "십")
    ones_first = min(v for (place, _), (_, v) in cells.items() if place == "일")
    band = (tens_last + half, ones_first - half)   # 설명이 들어가는 빈 구간

    _rect(pen, u0, top, u1, bottom)
    # 문번 칸과 구분선은 **덩어리마다 끊어서** 그린다.
    for run_top, run_bottom, corners in (
        (top, band[0], LEFT_ONLY if top == top else NO_CORNERS),
        (band[1], bottom, (False, False, False, True)),
    ):
        _rect(pen, u0, run_top, number_u, run_bottom, fill=TINT,
              corners=corners, stroke=False)
        _line(pen, number_u, run_top, number_u, run_bottom)
    _rect(pen, u0, top, u1, header_v, fill=TINT, corners=TOP_ONLY)
    _text(pen, (u0 + number_u) / 2, (top + header_v) / 2, "문번", size=8.6, bold=True)
    _text(pen, (number_u + u1) / 2, (top + header_v) / 2, "답    란", size=9.4, bold=True)
    _line(pen, u0, header_v, u1, header_v)
    _line(pen, number_u, top, number_u, band[0])

    for (place, digit), (u, v) in cells.items():
        heavy = digit in ("5", "0")
        _text(pen, (u0 + number_u) / 2, v, digit,
              size=11.7 if heavy else 10.6, bold=heavy)
        _cell(pen, u, v, "1")
        if place == "일" and digit == "5":
            # 원본은 폭의 40% 만 긋는 짧은 선이다 — 버블 오른쪽에서 끝난다.
            _line(pen, u0, v + half, u + float(L.BUBBLE_RU) + 0.006, v + half,
                  colour=GREEN, weight=1.2)

    _survey_notes(pen, u0, u1, band)


def _survey_notes(pen, u0, u1, band):
    """두 덩어리 사이의 설명 — 화살표가 위/아래 어느 쪽인지 말한다.

    글자는 **박스 안쪽 왼쪽 끝에 붙인다**(원본 실측 0.0~0.17mm). 들여쓰면
    줄이 짧아져 원본이 의도한 줄바꿈 자리가 어긋나 보인다.
    """
    top, bottom = band
    height = bottom - top
    arrow = height * 0.10
    line_step = height * 0.115
    _text(pen, (u0 + u1) / 2, top + arrow, "↑", size=9.0)
    v = top + arrow + line_step * 0.9
    for line in SURVEY_TENS_NOTE:
        _text(pen, u0 + 0.004, v, line, size=SURVEY_NOTE_PT, anchor="left")
        v += line_step
    mid = v - line_step * 0.35
    _line(pen, u0, mid, u1, mid, colour=GREEN, weight=1.2)
    v += line_step * 0.12
    for line in SURVEY_ONES_NOTE:
        _text(pen, u0 + 0.004, v, line, size=SURVEY_NOTE_PT, anchor="left")
        v += line_step
    _text(pen, (u0 + u1) / 2, bottom - arrow, "↓", size=9.0)


def _survey_side(pen, bu0, card):
    """★내 점수★ 손글씨 칸 + 예시 세 개(08·42·35점) — 원본 그대로."""
    box_w = float(L.mm_to_u(L.ANSWER_BOX_W_MM))
    pitch = float(L.mm_to_u(L.ANSWER_COL_PITCH_MM))
    bu1 = bu0 + box_w * 2 + (pitch - box_w)
    top, bottom = BOX_ANSWER_V
    hand_bottom = top + 0.250

    _rect(pen, bu0, top, bu1, hand_bottom, corners=NO_CORNERS)
    _text(pen, (bu0 + bu1) / 2, top + 0.045, "★  내 점수  ★", size=15.0, bold=True)

    # 원본에 있는 점 두 개 — 손으로 점수를 적는 자리를 짚어 준다.
    dot_u = bu0 + float(L.mm_to_u(Decimal("6.5")))
    for offset in (0.0, float(L.mm_to_v(Decimal("3.2")))):
        x, y = _xy(dot_u, top + 0.130 + offset)
        pen.setFillColor(INK)
        pen.circle(x, y, float(L.mm_to_u(Decimal("0.87"))) * float(L.SPAN_X_MM) * MM_UNIT,
                   stroke=0, fill=1)

    v = hand_bottom - 0.070
    for line in MYSCORE_NOTE:
        _text(pen, bu0 + 0.018, v, line, size=SURVEY_NOTE_PT, anchor="left")
        v += 0.030

    _survey_examples(pen, bu0, bu1, hand_bottom + 0.040, card)


def _survey_examples(pen, bu0, bu1, v0, card):
    """예시 세 벌 — **점수 열을 그대로 줄인 축소판**이다.

    십과 일 사이의 빈 구간까지 같은 비율로 담아야 원본과 같은 실루엣이 난다.
    그 구간을 접었더니 세로가 20mm 짧아 다른 물건처럼 보였다.
    """
    cells = card.survey_cells()
    scale = 0.68
    step = float(L.mm_to_v(L.ROW_PITCH_MM)) * scale
    span = bu1 - bu0
    width = span * 0.255
    gap = (span - width * len(SURVEY_EXAMPLES)) / (len(SURVEY_EXAMPLES) - 1 + 2.4)
    rows = {place: [d for (p, d) in cells if p == place]
            for place in ("십", "일")}
    tens_last = 4
    ones_first = 10          # 답란과 같은 20행 격자에서 일의 자리가 시작하는 행
    total_rows = ones_first + len(rows["일"])

    for index, (score, label) in enumerate(SURVEY_EXAMPLES):
        u0 = bu0 + gap * 1.2 + index * (width + gap)
        u1 = u0 + width
        number_u = u0 + width * 0.205
        head = v0 + 0.026
        first = head + 0.052
        bottom = first + (total_rows - 0.4) * step

        _text(pen, u0, v0, f"ex) {label}", size=8.6, anchor="left")
        _rect(pen, u0, head, u1, bottom)
        _rect(pen, u0, head, u1, head + 0.030, fill=TINT, corners=TOP_ONLY)
        _text(pen, (u0 + number_u) / 2, head + 0.015, "문번", size=5.0)
        _text(pen, (number_u + u1) / 2, head + 0.015, "답  란", size=5.4)
        _line(pen, u0, head + 0.030, u1, head + 0.030)

        marks = {"십": str(score // 10), "일": str(score % 10)}
        bubble_u = number_u + width * 0.20
        for place, row0 in (("십", 0), ("일", ones_first)):
            _rect(pen, u0, first + (row0 - 0.45) * step, number_u,
                  first + (row0 + len(rows[place]) - 0.55) * step,
                  fill=TINT, stroke=False, corners=NO_CORNERS)
            _line(pen, number_u, first + (row0 - 0.45) * step,
                  number_u, first + (row0 + len(rows[place]) - 0.55) * step)
            for order, digit in enumerate(rows[place]):
                v = first + (row0 + order) * step
                _text(pen, (u0 + number_u) / 2, v, digit, size=5.0)
                if marks[place] == digit:
                    _filled_bubble(pen, bubble_u, v)
                else:
                    _bubble(pen, bubble_u, v, float(L.BUBBLE_W_MM) * scale,
                            float(L.BUBBLE_H_MM) * scale)
                if place == "일" and digit == "5":
                    _line(pen, u0, v + step / 2,
                          bubble_u + float(L.BUBBLE_RU), v + step / 2,
                          colour=GREEN, weight=1.0)
        _ = tens_last


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

    pen.showPage()
    pen.save()
    return buffer.getvalue()

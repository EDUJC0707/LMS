"""카드 생성기 — `layout.py` 하나에서 **인쇄용 PDF** 와 **리더 좌표**를 함께 뽑는다.

이게 이 작업의 본체다. 지금 `card.py` 는 남의 카드를 재서 적은 **측정값**이라
판형과 리더가 어긋날 수 있었고, 실제로 어긋나서 보정 상수(`CALIBRATION_U/V`)가
생겼다. 생성기가 둘을 같이 뱉으면 **어긋날 수가 없다** — 같은 숫자로 그리고 같은
숫자로 읽는다.

    layout.py ──┬──▶ card-답안25.pdf   (인쇄 발주)
                └──▶ 리더 좌표          (generated_card.py)

## 왜 reportlab 인가

한글 라벨(성명·문번·자모 19자)을 벡터로 찍어야 하는데 `pypdf` 는 읽고 쓰는
도구지 그리는 도구가 아니다. 직접 PDF 콘텐츠 스트림을 쓰면 사각형·타원까지는
쉽지만 **한글은 CID 폰트를 심어야** 해서 그 자체로 한 덩어리 일이 된다.
reportlab 은 `UnicodeCIDFont('HYGothic-Medium')` 로 폰트 파일 없이 한글이 나온다.

## 인쇄 주의

- **배율 조정 없이(100%) 인쇄한다.** 호모그래피가 배율을 흡수하므로 판독은
  되지만, 축소되면 버블이 펜보다 작아진다
- 마커·판형 막대는 **검정 단색**이다. 컬러 보정이 들어가는 인쇄를 피할 것
"""
import io

from reportlab.lib.colors import black, white
from reportlab.lib.units import mm as MM_UNIT
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

from . import layout as L

FONT = "HYGothic-Medium"
_FONT_READY = False

#: 인쇄 안내 — 지면에 남기는 유일한 설명이다(운영 문구가 아니라 인쇄 지시다).
FOOTER = "※ 컴퓨터용 사인펜으로 마킹 · 수정은 수정테이프"


def _font():
    global _FONT_READY
    if not _FONT_READY:
        pdfmetrics.registerFont(UnicodeCIDFont(FONT))
        _FONT_READY = True
    return FONT


def _stroke():
    """인쇄 선 굵기(pt). 너무 얇으면 인쇄가 먹지 않고 렌더에서 링이 조각난다."""
    return float(L.STROKE_MM) * MM_UNIT


def _xy(u, v):
    """정규좌표 -> reportlab 포인트(좌하 원점)."""
    x_mm, y_mm = L.to_mm(u, v)
    return float(x_mm) * MM_UNIT, float(y_mm) * MM_UNIT


def _bubble(pen, u, v, width_mm, height_mm):
    """스타디움(세로로 긴 둥근 사각형) 테두리 한 칸."""
    x, y = _xy(u, v)
    w = float(width_mm) * MM_UNIT
    h = float(height_mm) * MM_UNIT
    pen.roundRect(x - w / 2, y - h / 2, w, h, min(w, h) / 2, stroke=1, fill=0)


def _label(pen, u, v, text, size=5.0, anchor="middle"):
    x, y = _xy(u, v)
    pen.setFont(_font(), size)
    draw = {"middle": pen.drawCentredString, "left": pen.drawString,
            "right": pen.drawRightString}[anchor]
    draw(x, y - size * 0.36, text)


def _fiducials(pen):
    """네 귀퉁이 마커 — 리더가 호모그래피를 푸는 네 점이다."""
    pen.setFillColor(black)
    w = float(L.MARK_W_MM) * MM_UNIT
    h = float(L.MARK_H_MM) * MM_UNIT
    for u in (0.0, 1.0):
        for v in (0.0, 1.0):
            x, y = _xy(u, v)
            pen.rect(x - w / 2, y - h / 2, w, h, stroke=0, fill=1)


def _layout_bars(pen, card):
    """판형 막대 — 좌우 대칭. 앵커 2 + 데이터 5비트 + 패리티(layout.encode_bars)."""
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


def _name_block(pen):
    """성명 자모 격자 — 8열x14행(초·종성) + 4열x19행(중성) = 188칸."""
    cells = L.name_cells()
    d = L.NAME_BUBBLE_D_MM
    pen.setStrokeColor(black)
    pen.setLineWidth(_stroke())
    for (col, row), (u, v) in cells.items():
        letters = L.VOWELS if col in L.NAME_VOWEL_COLUMNS else L.CONSONANTS
        _bubble(pen, u, v, d, d)
        _label(pen, u, v, letters[row - 1], size=3.6)
    top_v = float(L.NAME_ROW_V[0]) - 0.055
    _label(pen, float(L.NAME_COL_U[0]) - 0.004, top_v, "성   명   (좌측부터 차례로 마킹)",
           size=7, anchor="left")


def _phone_block(pen):
    """전화번호 끝 네 자리 — 4열 x 0~9."""
    for (pos, digit), (u, v) in L.phone_cells().items():
        _bubble(pen, u, v, L.BUBBLE_W_MM, L.BUBBLE_H_MM)
        _label(pen, u, v, str(digit), size=3.4)
    _label(pen, float(L.PHONE_COL_U[0]) - 0.004, float(L.PHONE_ROW_V[0]) - 0.055,
           "전화번호 끝 네 자리", size=7, anchor="left")


def _answer_block(pen, card):
    """답란 — 20행이 차면 다음 열. 열 1은 옛 카드와 같은 자리다."""
    cells = card.answer_cells()
    for question, choices in cells.items():
        for index, (u, v) in enumerate(choices, start=1):
            _bubble(pen, u, v, L.BUBBLE_W_MM, L.BUBBLE_H_MM)
            _label(pen, u, v, str(index), size=3.0)
        first_u = choices[0][0]
        _label(pen, first_u - 0.022, choices[0][1], str(question), size=5.2, anchor="right")
    for col in range(card.columns):
        u = float(L.mm_to_u(L.ANSWER_COL_X_MM + col * L.ANSWER_COL_PITCH_MM))
        _label(pen, u + 0.016, float(L.mm_to_v(L.ANSWER_FIRST_ROW_MM)) - 0.033,
               "문번        답    란", size=6, anchor="middle")


def _survey_block(pen):
    """성적 조사 — 점수 두 자리(십 1~5 · 일 1~9,0) + 손글씨 칸."""
    base_u = float(L.mm_to_u(L.ANSWER_COL_X_MM))
    top_v = float(L.mm_to_v(L.ANSWER_FIRST_ROW_MM))
    step_v = float(L.mm_to_v(L.ROW_PITCH_MM))
    gap_u = float(L.mm_to_u(L.CHOICE_PITCH_MM * 2))
    for column, digits in enumerate((L.SURVEY_TENS, L.SURVEY_ONES)):
        u = base_u + column * gap_u
        for row, digit in enumerate(digits):
            v = top_v + row * step_v
            _bubble(pen, u, v, L.BUBBLE_W_MM, L.BUBBLE_H_MM)
            _label(pen, u, v, digit, size=3.4)
        _label(pen, u, top_v - 0.033, "십" if column == 0 else "일", size=6)
    _label(pen, base_u + gap_u / 2, top_v - 0.062, "점    수", size=8)

    # ★내 점수★ — 버블을 안 칠하는 학생이 있어 손글씨 칸을 남긴다(설계 문서 §7).
    x, y = _xy(base_u + gap_u * 2.4, top_v + step_v * 3)
    w, h = 26 * MM_UNIT, 20 * MM_UNIT
    pen.setLineWidth(_stroke() * 2)
    pen.rect(x, y - h, w, h, stroke=1, fill=0)
    _label(pen, base_u + gap_u * 2.4 + float(L.mm_to_u(13)), top_v - 0.02,
           "★내 점수★", size=7)


def render(card, title="한종철 생명과학", subtitle=""):
    """카드 한 장을 PDF 바이트로. `card` 는 `layout.Layout`."""
    buffer = io.BytesIO()
    pen = canvas.Canvas(
        buffer, pagesize=(float(L.PAGE_W_MM) * MM_UNIT, float(L.PAGE_H_MM) * MM_UNIT)
    )
    pen.setTitle(f"{title} — {card.name}")
    pen.setFillColor(white)
    pen.rect(0, 0, float(L.PAGE_W_MM) * MM_UNIT, float(L.PAGE_H_MM) * MM_UNIT,
             stroke=0, fill=1)
    pen.setFillColor(black)
    pen.setStrokeColor(black)
    pen.setLineWidth(_stroke())

    _fiducials(pen)
    _layout_bars(pen, card)
    _name_block(pen)
    _phone_block(pen)
    if card.is_survey:
        _survey_block(pen)
    else:
        _answer_block(pen, card)

    _label(pen, 0.0, -0.045, title, size=11, anchor="left")
    if subtitle:
        _label(pen, 0.0, -0.012, subtitle, size=7, anchor="left")
    _label(pen, 1.0, 1.045, FOOTER, size=5.5, anchor="right")
    # 판형 이름을 사람 눈에도 남긴다 — 발주·보관에서 섞이면 곤란하다.
    _label(pen, 1.0, -0.045, card.name, size=7, anchor="right")

    pen.showPage()
    pen.save()
    return buffer.getvalue()

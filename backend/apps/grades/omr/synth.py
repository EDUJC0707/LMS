"""마킹된 카드 이미지를 만든다 — **학생이 실제로 하는 짓까지.**

새 카드는 여기까지 오는 동안 판독기를 한 번도 통과한 적이 없었다. 검증이 전부
"렌더된 PDF 를 자로 재는 것"이었기 때문이다 — 링이 설계 좌표에 있는지는 확인
했지만, 그 링을 칠했을 때 리더가 그걸 읽는지는 아무도 안 봤다.

## 왜 깨끗한 마킹만으로는 부족한가

실물에서 걸리는 것은 늘 지저분한 쪽이다. 옛 카드 65장에서도 칸 밖으로 삐져나간
마킹 2건 때문에 표본 반경을 넓혀야 했고, 그런 것은 **깨끗한 합성 픽스처에서는
영원히 안 나온다.** 그래서 마킹 방식을 파라미터로 둔다:

| | |
|---|---|
| `full` | 제대로 꽉 칠했다 |
| `light` | 연필이 약하다 |
| `half` | 아래 절반만 칠했다 |
| `spill` | 칸 옆으로 삐져나갔다 |
| `circle` | 링만 덧그렸다(안을 안 채웠다) |
| `check` | 체크 표시만 했다 |
| `slash` | 사선 하나로 그었다 |
| `erased` | 칠했다 지운 자국 — 옅게 남는다 |

스캐너 쪽 열화는 `degrade` 가 따로 얹는다(회전·흐림·JPEG·밝기·잡음).

## 지면 방향

실제 스캔은 **세로**다 — A4 를 짧은 변부터 먹이므로 카드가 90° 누워 들어온다.
`page` 가 렌더를 그 방향으로 돌려서 내놓는다.
"""
import subprocess
import tempfile
from pathlib import Path

import cv2
import numpy as np

from . import decode, generate, normalize

#: 진하게 칠한 연필의 밝기. 실물 마커 인쇄가 중앙값 58~67 이므로 그보다 진하다.
INK_DARK = 35
#: 옅게 칠한 연필. 판정 문턱 근처를 재려고 둔다.
INK_LIGHT = 130
#: 지운 자국 — 종이(255)와 옅은 연필 사이.
INK_ERASED = 205

STYLES = ("full", "light", "half", "spill", "circle", "check", "slash", "erased")


def page(card, dpi=200):
    """빈 카드 한 장 — **실제 스캔과 같은 세로 방향**의 그레이스케일."""
    with tempfile.TemporaryDirectory() as tmp:
        pdf = Path(tmp) / "card.pdf"
        pdf.write_bytes(generate.render(card))
        subprocess.run(
            ["pdftoppm", "-png", "-r", str(dpi), str(pdf), str(Path(tmp) / "p")],
            check=True, capture_output=True,
        )
        raw = cv2.imread(str(next(Path(tmp).glob("p*.png"))), 0)
    return cv2.rotate(raw, cv2.ROTATE_90_CLOCKWISE)


def _jamo(syllable):
    """한글 음절 -> (초성, 중성, 종성). 종성이 없으면 빈 문자열."""
    code = ord(syllable) - decode.SYLLABLE_BASE
    return (
        decode.UNICODE_LEADS[code // decode.LEAD_SPAN],
        decode.UNICODE_VOWELS[(code % decode.LEAD_SPAN) // decode.VOWEL_SPAN],
        decode.UNICODE_TAILS[code % decode.VOWEL_SPAN].strip(),
    )


def name_marks(name):
    """이름 -> 칠할 성명칸 `{(열, 행)}`.

    **카드가 표현 못 하는 자모는 낮춰서 칠한다** — 학생이 실제로 그렇게 한다
    (`꽃님` 은 `곷님` 으로 들어온다). 낮춤표는 판독 쪽과 같은 것을 쓴다.
    """
    marks = set()
    for slot, syllable in enumerate(name[: decode.NAME_SLOTS]):
        lead, vowel, tail = _jamo(syllable)
        for offset, (jamo, table) in enumerate((
            (lead, decode.CARD_CONSONANTS),
            (vowel, decode.CARD_VOWELS),
            (tail, decode.CARD_CONSONANTS),
        )):
            folded = decode.CARD_FOLD.get(jamo, jamo)
            if folded:
                marks.add((3 * slot + offset + 1, table.index(folded) + 1))
    return marks


def phone_marks(digits):
    """전화 뒷 4자리 -> 칠할 칸 `{(자리, 숫자)}`."""
    return {(pos, int(digit)) for pos, digit in enumerate(str(digits), start=1)}


def _pixel_radius(frame, u, v, ru, rv):
    """정규 반경을 그 자리에서의 픽셀 반경으로 — 사영변환이라 자리마다 다르다."""
    centre = frame.to_source(u, v)
    across = frame.to_source(u + ru, v) - centre
    down = frame.to_source(u, v + rv) - centre
    return centre, float(np.linalg.norm(across)), float(np.linalg.norm(down))


def draw_mark(image, frame, point, radius, style="full"):
    """칸 하나를 학생이 칠한 것처럼 그린다. `style` 은 모듈 docstring 의 표."""
    (u, v), (ru, rv) = point, radius
    centre, half_w, half_h = _pixel_radius(frame, u, v, ru, rv)
    x, y = int(round(centre[0])), int(round(centre[1]))
    w, h = max(int(round(half_w)), 1), max(int(round(half_h)), 1)
    if style in ("full", "light", "erased"):
        tone = {"full": INK_DARK, "light": INK_LIGHT, "erased": INK_ERASED}[style]
        cv2.ellipse(image, (x, y), (w, h), 0, 0, 360, tone, -1)
    elif style == "half":
        cv2.ellipse(image, (x, y), (w, h), 0, 0, 180, INK_DARK, -1)
    elif style == "spill":
        # 칸 오른쪽으로 밀려 나간 마킹 — 옛 카드에서 표본 반경을 넓히게 만든 경우다.
        cv2.ellipse(image, (x + int(w * 0.7), y), (w, h), 0, 0, 360, INK_DARK, -1)
    elif style == "circle":
        cv2.ellipse(image, (x, y), (w, h), 0, 0, 360, INK_DARK, max(w // 3, 2))
    elif style == "check":
        cv2.line(image, (x - w, y), (x - w // 3, y + h), INK_DARK, max(w // 2, 2))
        cv2.line(image, (x - w // 3, y + h), (x + w, y - h), INK_DARK, max(w // 2, 2))
    elif style == "slash":
        cv2.line(image, (x - w, y + h), (x + w, y - h), INK_DARK, max(w // 2, 2))
    else:
        raise ValueError(f"모르는 마킹 방식: {style!r}")
    return image


def sheet(card, grid, answers, *, name=None, phone=None, extra=(),
          style="full", styles=None, dpi=200, image=None):
    """마킹된 답안 카드 한 장.

    `answers` 는 `{문항: 선택지}` 또는 `{문항: (선택지, ...)}`(복수 마킹).
    `styles` 로 문항마다 다른 방식을 줄 수 있다 — 안 주면 전부 `style` 이다.
    `extra` 는 약점 체크를 칠할 문항 번호들.
    """
    image = page(card, dpi) if image is None else image
    frame = normalize.locate_card(image)
    if frame is None:
        raise RuntimeError("합성 지면에서 카드를 못 찾았다 — 픽스처가 잘못됐다.")
    styles = styles or {}
    answer_points = dict(grid.answer)
    for question, choices in answers.items():
        for choice in (choices,) if isinstance(choices, int) else choices:
            draw_mark(image, frame, answer_points[(question, choice)],
                      grid.answer_radius, styles.get(question, style))
    extra_points = dict(grid.extra)
    for question in extra:
        draw_mark(image, frame, extra_points[(question, 1)], grid.answer_radius,
                  styles.get(question, style))
    if name:
        points = dict(grid.names)
        for key in name_marks(name):
            draw_mark(image, frame, points[key], grid.name_radius, style)
    if phone:
        points = dict(grid.phones)
        for key in phone_marks(phone):
            draw_mark(image, frame, points[key], grid.phone_radius, style)
    return image


def degrade(image, *, angle=0.0, blur=0, jpeg=None, brightness=0,
            contrast=1.0, noise=0, rng=None):
    """스캐너를 통과한 것처럼 망가뜨린다.

    회전은 **화폭을 넓혀서** 한다 — 고정 화폭으로 돌리면 프레임을 세우는 마커가
    잘려 나가고, 그러면 기울기가 아니라 잘림을 재게 된다.
    """
    rng = rng or np.random.default_rng(0)
    out = image
    if angle:
        height, width = out.shape
        matrix = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1.0)
        cos, sin = abs(matrix[0, 0]), abs(matrix[0, 1])
        grown = (int(height * sin + width * cos), int(height * cos + width * sin))
        matrix[0, 2] += grown[0] / 2 - width / 2
        matrix[1, 2] += grown[1] / 2 - height / 2
        out = cv2.warpAffine(out, matrix, grown, borderValue=255)
    if blur:
        size = 2 * int(blur) + 1
        out = cv2.GaussianBlur(out, (size, size), 0)
    if brightness or contrast != 1.0:
        out = np.clip(out.astype(np.float32) * contrast + brightness, 0, 255).astype(np.uint8)
    if noise:
        out = np.clip(
            out.astype(np.int16) + rng.integers(-noise, noise + 1, out.shape), 0, 255
        ).astype(np.uint8)
    if jpeg is not None:
        ok, blob = cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, int(jpeg)])
        if not ok:
            raise RuntimeError("JPEG 인코딩 실패")
        out = cv2.imdecode(blob, cv2.IMREAD_GRAYSCALE)
    return out

"""회차 드리프트 — 이 배치의 격자가 `card.py` 가 말하는 자리에 있나.

## 왜 필요한가

카드를 찍을 때마다 배치가 미세하게 달라진다. 실측: **3월 카드와 6월 카드가
4.9px 어긋나 있었다.** 좌표는 실물로 맞춰 뒀지만 다음 회차가 또 밀리면
아무 신호 없이 10~20장이 틀린다 — 격자가 밀려도 여전히 버블 위에 얹히기 때문에
판독은 자신 있게 **다른 답**을 내놓는다.

그래서 배치마다 **재는 것**이 이 모듈이다. 고치지는 않는다:

- 자동으로 좌표를 옮기면 그날 스캐너가 이상했던 것까지 판형으로 굳는다
- 사람이 값을 보고 `card.py` 를 고치는 것이 되돌릴 수 있는 유일한 경로다

## 어떻게 재나

배치를 마커 정규좌표로 정합해 **평균 낸다.** 연필은 장마다 다른 자리에 있어
평균에서 묻히고 **인쇄된 버블 테두리만 남는다.** 그 평면에서 답란 첫 열의
잉크 프로파일을 예측 격자와 견줘, 몇 px 밀렸는지 낸다.

한 장으로는 못 잰다 — 그 장의 접힘인지 회차의 이동인지 못 가른다. 여러 장의
평균에서만 "이 배치 전체가 밀렸다"가 보인다.
"""
import cv2
import numpy as np

from . import card, normalize

#: 평균판 크기 — card 의 평균판 좌표계(2223.5 x 1493.5)와 같은 축.
PLATE = (2224, 1494)
#: 이 값을 넘으면 사람에게 알린다. 버블 반높이가 16.6px 이고 표본은 그 65%(10.8px)만
#: 쓰므로 여유가 약 5.8px 다 — 그 절반에서 경고한다(실측 회차 간 이동 4.9px).
WARN_PX = 3.0
#: 평균이 인쇄만 남기려면 장이 이만큼은 있어야 한다. 그 아래는 연필이 안 묻힌다.
MIN_SHEETS = 8


class Accumulator:
    """장을 하나씩 받아 평균판을 쌓는다 — 이미지를 들고 있지 않는다.

    한 묶음이 65장이고 장당 3.8MB 라 전부 들고 있으면 250MB 다. 정합한 평면을
    더해 가면 **한 장 분량**(13MB)만 있으면 된다.
    """

    __slots__ = ("_total", "_sheets")

    def __init__(self):
        self._total = None
        self._sheets = 0

    def add(self, image):
        frame = normalize.locate_card(image)
        if frame is None:
            return
        warped = _warp(image, frame)
        self._total = warped if self._total is None else self._total + warped
        self._sheets += 1

    def result(self):
        if self._sheets < MIN_SHEETS:
            return None
        return _from_plate(self._total / self._sheets, self._sheets)


def measure(images):
    """스캔 여러 장 → `{"sheets", "dv", "warn"}`. 못 재면 None.

    `dv` 는 답란이 예측보다 **아래로** 밀린 px(평균판 기준, 음수면 위로).
    가로 방향은 열 간격이 41px 로 촘촘해 같은 방법으로는 안 갈려 재지 않는다 —
    실측에서 회차 간 이동도 세로였다.
    """
    accumulator = Accumulator()
    for image in images:
        accumulator.add(image)
    return accumulator.result()


def _warp(image, frame):
    target = np.array(
        [[0, 0], [PLATE[0], 0], [PLATE[0], PLATE[1]], [0, PLATE[1]]], dtype=np.float32
    )
    matrix = cv2.getPerspectiveTransform(frame.corners.astype(np.float32), target)
    return cv2.warpPerspective(image, matrix, PLATE).astype(np.float32)


def _from_plate(plate, sheets):
    """평균판 → 측정 결과."""
    predicted = [v * 1493.5 for (question, choice), (u, v) in card.answer_cells() if choice == 1]
    column_x = card.answer_cells()[0][1][0] * 2223.5
    strip = 255.0 - plate[:, int(column_x) - 9 : int(column_x) + 10].mean(axis=1)
    offsets = _ring_offsets(strip, predicted)
    if len(offsets) < len(predicted) // 2:
        # 링을 절반도 못 찾았다 — 잴 근거가 없으므로 지어내지 않는다.
        return None
    dv = float(np.median(offsets))
    return {"sheets": sheets, "dv": round(dv, 2), "warn": abs(dv) >= WARN_PX}


def _ring_offsets(strip, predicted, window=22):
    """행마다 인쇄 링의 실제 중심을 찾아 예측과의 차이를 모은다.

    **잉크를 최대화하지 않는다.** 버블은 속이 빈 스타디움이라 잉크가 테두리에
    있고, 안쪽에는 인쇄된 ①~⑤ 글자가 있다 — 중심 주변 잉크를 세면 링이 아니라
    그 글자를 재게 되어 전 회차가 똑같이 밀려 보인다(첫 판에서 실제로 그랬다).

    대신 예측 중심 위아래에서 **잉크 봉우리 둘**(링의 윗변·아랫변)을 찾고 그
    가운데를 실제 중심으로 삼는다. 한쪽 변만 보이면 그 행은 버린다.
    """
    offsets = []
    for centre in predicted:
        low, high = int(centre) - window, int(centre) + window + 1
        if low < 0 or high > len(strip):
            continue
        piece = strip[low:high]
        middle = len(piece) // 2
        top, bottom = piece[:middle], piece[middle:]
        if top.max() <= 0 or bottom.max() <= 0:
            continue
        edge_top = int(np.argmax(top))
        edge_bottom = middle + int(np.argmax(bottom))
        offsets.append(low + (edge_top + edge_bottom) / 2 - centre)
    return offsets

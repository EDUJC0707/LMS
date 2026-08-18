"""판형 막대 읽기 — **스캔 원본에서, 호모그래피보다 먼저** 돈다.

왜 먼저인가: 셀을 표본하려면 판형을 알아야 하고(어느 격자인지), 판형을 알려면
지면을 읽어야 한다. 버블로 판형을 적으면 이 순환이 안 풀린다 — 프레임을 먼저
세워야 버블을 표본할 수 있기 때문이다. 가장자리 막대는 **덩어리를 세기만** 하면
되므로 원본에서 바로 읽힌다.

## 어떻게 어긋남을 견디나

- **앵커 두 개가 좌표계를 만든다.** 첫·끝 막대는 항상 인쇄되므로, 검출된 막대의
  최상·최하가 곧 슬롯 0 과 7 이다. 거기서 간격을 역산하니 **배율·평행이동이
  통째로 흡수된다** — 스캐너가 확대하든 종이가 밀려 들어가든 같은 답이 나온다
- **기울기는 변마다 따로 푼다.** 좌우를 독립으로 읽으므로 회전은 각 변 안에서
  일정한 배율 변화로 나타나고, 그것도 앵커가 흡수한다
- **한쪽이 잘려도 반대쪽으로 읽는다.** 스캔에서 가장자리가 날아가는 일이 있다
- **둘이 다르면 안 읽는다.** 조용히 틀리느니 보류가 낫다(`decode_bars` 의 패리티도
  같은 축)

## 한계

막대가 아예 없으면 `None` 이다 — 옛 튜터시스템 카드가 그렇고, 그쪽은 종전대로
`exams.kind` 로 판형을 정한다.
"""
import cv2
import numpy as np

from . import layout as L
from .normalize import dark_threshold

#: 가장자리에서 이 비율 안쪽까지가 막대 자리. 마커도 같은 열에 있지만 모양이
#: 다르다(마커 1.27x2.41mm 비율 1.9 · 막대 1.10x7.62mm 비율 6.9) — 세로비로 갈린다.
EDGE_BAND = 0.075
MIN_ASPECT = 3.5
MAX_ASPECT = 14.0
#: 지면 높이 대비 막대 높이(7.62/210 = 3.6%). 스캔 해상도를 몰라도 되게 비율로 잡는다.
MIN_H_RATIO = 0.018
MAX_H_RATIO = 0.065
#: 슬롯 자리에서 이만큼(간격 대비) 안에 있으면 그 슬롯으로 본다.
SLOT_TOLERANCE = 0.34


def _candidates(image):
    """막대로 볼 만한 성분 — (x, y) 목록."""
    height, width = image.shape
    mask = (image < dark_threshold(image)).astype(np.uint8)
    count, _, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
    found = []
    for index in range(1, count):
        w = stats[index, cv2.CC_STAT_WIDTH]
        h = stats[index, cv2.CC_STAT_HEIGHT]
        if w <= 0 or not (MIN_H_RATIO * height <= h <= MAX_H_RATIO * height):
            continue
        if not (MIN_ASPECT <= h / w <= MAX_ASPECT):
            continue
        area = stats[index, cv2.CC_STAT_AREA]
        if area < 0.55 * w * h:  # 속이 찬 막대다. 링이나 글자가 아니다
            continue
        cx, cy = centroids[index]
        if not (cx < EDGE_BAND * width or cx > (1 - EDGE_BAND) * width):
            continue
        found.append((cx, cy))
    return found


def _read_side(ys):
    """한 변의 막대 y 목록 -> 판형 id. 못 읽으면 None.

    최상·최하를 앵커로 보고 간격을 역산한다 — 그래서 배율·평행이동을 안 탄다.
    """
    if len(ys) < 2:
        return None
    ys = sorted(ys)
    first, last = ys[0], ys[-1]
    pitch = (last - first) / (L.BAR_SLOTS - 1)
    if pitch <= 0:
        return None
    slots = []
    for slot in range(L.BAR_SLOTS):
        expected = first + slot * pitch
        slots.append(any(abs(y - expected) <= pitch * SLOT_TOLERANCE for y in ys))
    # 앵커 사이에 들어가지 않는 막대가 있으면 이 변은 못 믿는다.
    if sum(slots) != len(ys):
        return None
    return L.decode_bars(slots)


def read_layout(image):
    """스캔 원본(그레이스케일) -> 판형 id. 못 읽으면 None.

    좌우를 따로 읽는다. 둘 다 읽혔는데 다르면 **보류**(None) — 한쪽이 오염됐다는
    뜻이라 어느 쪽을 믿을지 알 수 없다.
    """
    width = image.shape[1]
    found = _candidates(image)
    left = _read_side([y for x, y in found if x < width / 2])
    right = _read_side([y for x, y in found if x >= width / 2])
    if left is not None and right is not None:
        return left if left == right else None
    return left if left is not None else right

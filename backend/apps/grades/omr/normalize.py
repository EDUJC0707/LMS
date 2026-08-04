"""스캔 이미지 → 카드 자리. **이미지만 알고 카드 내용은 모른다**(PRD 3.1.1).

이 모듈이 답하는 질문은 하나다 — "이 스캔에서 카드가 어디에 어떻게 놓였나".
무엇이 마킹인지, 그 마킹이 무슨 뜻인지는 여기 소관이 아니다. 판형이 바뀌어도
네 모서리 마커는 그대로이므로 이 모듈은 그대로 산다.

## 왜 마커인가

실측(2026-08-04, 실제 스캔 65장)에서 나온 것:

- 좌상단 마커가 장마다 **x 52px · y 76px** 범위로 움직인다 → 절대 좌표는 못 쓴다
- 마커 간격이 공칭 200dpi 기준값의 **0.948배** → 공칭 DPI 를 믿으면 안 된다
- 기울기 median -0.24°, **최대 -3.55°**
- 아래 변이 위 변보다 2.5~9.5px 넓다(사다리꼴) → 회전 보정만으로는 부족하다

그래서 좌표는 전부 **마커 기준 상대값**이고, 변환은 4점 사영변환이다.

## 마커 판별 기준

채워진 검은 사각형이고 **좌우 폭이 다르다**(좌 ~21px, 우 ~36px). 이 비대칭은
상하·좌우 뒤집힘을 가리는 근거가 되므로 나중에 쓴다.

채움률 하한 0.70 은 실측에서 나온 값이다 — 0.85 로 잡으면 기울어진 장에서
안티에일리어싱으로 가장자리가 흐려져 65장 중 3장을 놓친다.
"""
import cv2
import numpy as np

#: 인쇄는 드롭아웃 잉크라 스캔에서 연회색으로 죽고 마커·연필 마킹만 진하게 남는다.
DARK_MAX = 100
#: 마커 크기 허용 범위(px @200dpi) — 실측 좌 21x18 · 우 36x18 에 여유를 둔 값.
MARK_MIN_W, MARK_MAX_W = 15, 50
MARK_MIN_H, MARK_MAX_H = 12, 30
MARK_MIN_AREA = 250
#: 채움률 하한 — 모듈 docstring 참조. 낮추면 글자 획이 섞인다.
MARK_MIN_FILL = 0.70
#: 마커가 있을 수 있는 띠 — 상·하 각 14%, 좌·우 각 20%.
#: **네 방향을 다 걸러야 한다.** 상하만 걸렀더니 헤더 제목 글자가 마커 크기·채움률을
#: 그대로 통과해 65장 중 39장에서 후보가 5~8개로 불어났다(2026-08-04 실측).
#: 글자는 마커와 모양으로는 안 갈리고 **자리로만** 갈린다.
BAND = 0.14
SIDE_BAND = 0.20


#: 카드 정규좌표의 기준 사각형 — (0,0) 좌상 마커, (1,1) 우하 마커.
UNIT_SQUARE = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], dtype=np.float32)


class CardFrame:
    """이 스캔에서 카드가 놓인 자리. 정규좌표 → 원본 픽셀 변환을 들고 있다.

    정규좌표는 **마커 네 점이 만드는 단위 사각형**이다. 카드 위 모든 자리를
    "마커 간격의 몇 분의 몇"으로 적으면 배율·기울기·사다리꼴이 전부 변환에
    흡수된다 — 실측에서 배율이 공칭의 0.948배였고 장마다 또 달랐다.
    """

    def __init__(self, corners):
        self.corners = corners
        self._matrix = cv2.getPerspectiveTransform(
            UNIT_SQUARE, corners.astype(np.float32)
        )

    def to_source(self, u, v):
        """정규좌표 (u, v) → 원본 픽셀 (x, y)."""
        x, y, w = self._matrix @ np.array([u, v, 1.0], dtype=np.float64)
        return np.array([x / w, y / w])


def locate_card(image):
    """스캔에서 카드 자리를 찾는다. 마커를 못 찾으면 None(호출부가 보류로 돌린다)."""
    corners = find_corner_marks(image)
    if corners is None:
        return None
    return CardFrame(corners)


def find_corner_marks(image):
    """네 모서리 마커 중심을 **좌상·우상·우하·좌하** 순으로. 4개가 아니면 None.

    시계방향으로 돌려주는 이유는 cv2.getPerspectiveTransform 이 그 순서를 받기
    때문이다 — 호출부마다 다시 정렬하면 한 곳만 틀려도 조용히 뒤집힌다.
    """
    candidates = _mark_candidates(image)
    if len(candidates) < 4:
        return None
    return _nearest_to_page_corners(candidates, image.shape)


def _mark_candidates(image):
    """마커로 볼 만한 성분의 중심 목록 — 크기·채움률·위치로 거른다."""
    height, width = image.shape
    count, _, stats, centroids = cv2.connectedComponentsWithStats(
        (image < DARK_MAX).astype(np.uint8), connectivity=8
    )
    found = []
    for index in range(1, count):
        w = stats[index, cv2.CC_STAT_WIDTH]
        h = stats[index, cv2.CC_STAT_HEIGHT]
        area = stats[index, cv2.CC_STAT_AREA]
        if not (MARK_MIN_W <= w <= MARK_MAX_W and MARK_MIN_H <= h <= MARK_MAX_H):
            continue
        if area < MARK_MIN_AREA or area / (w * h) < MARK_MIN_FILL:
            continue
        cx, cy = centroids[index]
        if BAND * height < cy < (1 - BAND) * height:
            continue
        if SIDE_BAND * width < cx < (1 - SIDE_BAND) * width:
            continue
        found.append((cx, cy))
    return found


def _nearest_to_page_corners(points, shape):
    """페이지 네 모서리에 각각 가장 가까운 후보를 좌상·우상·우하·좌하 순으로.

    띠 안에 후보가 더 있어도 **모서리에서 더 먼 것**이라 자연히 밀려난다(실물
    all-059: 진짜 마커는 모서리에서 158px, 오인 덩어리는 365px). 띠 폭을 좁혀
    떨구는 방식은 표본에 맞춘 튜닝이라 다음 스캔에서 다시 깨진다.

    한 후보가 두 모서리에 동시에 뽑히면(=한 귀퉁이에 마커가 없다) None —
    억지로 네 점을 만들면 변환이 조용히 뒤틀린다.
    """
    height, width = shape
    targets = ((0, 0), (width, 0), (width, height), (0, height))
    chosen = [
        min(points, key=lambda p: (p[0] - tx) ** 2 + (p[1] - ty) ** 2)
        for tx, ty in targets
    ]
    if len({(round(x, 3), round(y, 3)) for x, y in chosen}) != 4:
        return None
    return np.array(chosen, dtype=np.float64)

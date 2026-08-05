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
#: 카드 위쪽 마커가 아래쪽보다 이만큼은 커야 방향을 가렸다고 본다.
#: 실측 비는 1.7배(648 대 378)이므로 1.25 는 넉넉한 하한이다.
MARK_AREA_RATIO = 1.25

#: 마커 사각형 검증 한계 — 실측 65장(2026-08-05) 분포: 대변 길이비 최대 1.0072,
#: 모서리각 90° 이탈 최대 0.31°, 종횡비 1.4822~1.4891(빈 카드 1.4887).
#: 한계는 실측 최악값의 6~10배 밖이다. 넘으면 마커 오인이므로 보류가 맞다.
#: 표본이 스캐너 1대·인쇄 1회차뿐이라 여유를 넓게 남긴다 — 분포를 다시 재면 조인다.
QUAD_MAX_OPPOSITE_RATIO = 1.05
QUAD_MAX_ANGLE_DEV = 3.0
QUAD_ASPECT_MIN, QUAD_ASPECT_MAX = 1.40, 1.60


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
    """스캔에서 카드 자리를 찾는다. 못 찾거나 방향을 못 가리면 None(보류).

    돌려주는 프레임의 정규좌표는 **카드 자신의** 방향이다 — 카드는 세로 페이지에
    누워 들어오지만 (0,0) 은 언제나 카드의 좌상단이다. 눕는 방향을 코드에 박지
    않는 이유는 급지가 뒤집힌 날 전부 조용히 어긋나기 때문이다.
    """
    found = _corner_marks_with_area(image)
    if found is None:
        return None
    oriented = _roll_to_card_top_left(*found)
    if oriented is None:
        return None
    return CardFrame(oriented)


def find_corner_marks(image):
    """네 모서리 마커 중심을 **스캔 기준** 좌상·우상·우하·좌하 순으로. 못 찾으면 None.

    여기까지가 검출이고 카드가 어느 쪽으로 누웠는지는 모른다 — 그 해석은
    locate_card 의 몫이다.
    """
    found = _corner_marks_with_area(image)
    return None if found is None else found[0]


def _corner_marks_with_area(image):
    """(중심 4x2, 면적 4) 또는 None — 검출의 공통 부분."""
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
        found.append((cx, cy, float(area)))
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
    if len({(round(p[0], 3), round(p[1], 3)) for p in chosen}) != 4:
        return None
    picked = np.array(chosen, dtype=np.float64)
    if not _plausible_quad(picked[:, :2]):
        return None
    return picked[:, :2], picked[:, 2]


def _plausible_quad(corners):
    """네 점이 카드 마커 사각형답게 생겼는가 — 대변비·종횡비·모서리각·볼록.

    진짜 마커가 하나 빠지고 잡티가 그 모서리에 더 가까우면 nearest 선택은 잡티를
    그대로 물고, 이후 좌표가 전부 조용히 어긋난다. 실물 재현(all-000 의 좌상 마커를
    가리고 all-059 에서 나온 자리에 잡티를 그림): 사각형이 멀쩡히 반환됐고 카드
    중앙이 **49.3px** 밀렸다 — 선택지 열 간격 38.9px 보다 크다. 아무 신호 없이
    한 칸 밀린 답이 성적표로 나간다.

    그 사각형은 기하가 실측 분포를 크게 벗어난다(대변비 1.146 · 각 이탈 11.1°).
    **종횡비만으로는 못 잡는다**(그 사례가 1.5432 로 범위 안) — 대변비와 각이
    각각 단독으로 걸러 내므로 넷을 함께 본다.
    """
    top, right, bottom, left = (
        float(np.linalg.norm(corners[(i + 1) % 4] - corners[i])) for i in range(4)
    )
    if min(top, right, bottom, left) < 1.0:
        return False
    if max(top, bottom) > QUAD_MAX_OPPOSITE_RATIO * min(top, bottom):
        return False
    if max(left, right) > QUAD_MAX_OPPOSITE_RATIO * min(left, right):
        return False
    axis_a, axis_b = (left + right) / 2, (top + bottom) / 2
    aspect = max(axis_a, axis_b) / min(axis_a, axis_b)
    if not QUAD_ASPECT_MIN <= aspect <= QUAD_ASPECT_MAX:
        return False
    crosses = []
    for index in range(4):
        to_prev = corners[(index - 1) % 4] - corners[index]
        to_next = corners[(index + 1) % 4] - corners[index]
        # 2 차원 np.cross 는 numpy 2.0 에서 폐기 예정이라 수식으로 쓴다.
        crosses.append(to_prev[0] * to_next[1] - to_prev[1] * to_next[0])
        cosine = np.dot(to_prev, to_next) / (
            np.linalg.norm(to_prev) * np.linalg.norm(to_next)
        )
        angle = np.degrees(np.arccos(np.clip(cosine, -1.0, 1.0)))
        if abs(angle - 90.0) > QUAD_MAX_ANGLE_DEV:
            return False
    return all(c > 0 for c in crosses) or all(c < 0 for c in crosses)


def _roll_to_card_top_left(corners, areas):
    """스캔 순서(4x2)를 **카드 자신의** 좌상·우상·우하·좌하 순으로 돌린다.

    카드 위쪽 변의 마커가 아래쪽보다 길다(실측: 면적 648 대 378, 1.7배). 시계방향
    순서에서 **큰 마커 둘이 이웃한 자리**가 곧 카드의 위쪽 변이고, 그 변을 시계방향
    으로 지나는 첫 점이 카드의 좌상단이다.

    큰 쪽과 작은 쪽이 충분히 안 벌어지면 None — 억지로 방향을 정하느니 보류로
    보낸다. 여기서 한 칸 틀리면 성명란을 답란으로 읽는다.
    """
    order = np.argsort(areas)
    if areas[order[2]] < MARK_AREA_RATIO * areas[order[1]]:
        return None
    is_long = np.zeros(4, dtype=bool)
    is_long[order[2:]] = True
    for index in range(4):
        if is_long[index] and is_long[(index + 1) % 4]:
            return np.roll(corners, -index, axis=0)
    return None

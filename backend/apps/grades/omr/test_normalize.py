"""정규화 계약 — 스캔 이미지에서 카드가 어디에 놓였는지 찾는다.

**테스트가 카드를 직접 그린다.** 실제 스캔본은 지면에 실명·전화 뒷4가 찍혀 있어
저장소에 넣을 수 없다(CLAUDE.md §5). 대신 마커를 아는 자리에 찍고 기울기·배율을
일부러 넣은 이미지를 만들어, 정규화가 그 변환을 되찾는지 본다 — 정답을 우리가
만드니 실물 픽스처보다 오히려 정확하다.

합성 값은 실측에서 가져왔다(2026-08-04, 실제 스캔 65장):
- 1651x2335 · 200dpi 8bit 흑백
- 마커는 네 모서리의 채워진 검은 사각형. **좌우 폭이 다르다**(좌 ~21px, 우 ~36px)
- 실물 기울기 median -0.24°, 최대 -3.55°
"""
import cv2
import numpy as np

from . import normalize

# 실측 페이지 1 기준 마커 중심(x, y)과 크기(w, h).
SCAN_SIZE = (1651, 2335)  # (w, h)
MARKS = (
    ((115.0, 120.0), (21, 18)),  # 좌상
    ((1525.0, 120.0), (36, 18)),  # 우상
    ((1525.0, 2225.0), (36, 18)),  # 우하
    ((115.0, 2225.0), (21, 18)),  # 좌하
)
CORNERS = np.array([c for c, _ in MARKS], dtype=np.float64)
#: 카드 정규좌표 순서(카드 좌상·우상·우하·좌하) → 스캔 모서리 순서(MARKS) 대응.
#: 카드는 세로 페이지에 **90° 시계방향으로 누워** 들어오므로 카드의 좌상단은
#: 스캔의 우상단이다. 긴 마커(폭 36)가 붙은 변이 카드의 위쪽 변이다.
CARD_TO_SCAN = [1, 2, 3, 0]


#: 상·하단 띠 **가운데**에 놓인 마커 크기의 검은 덩어리 — 실물에서는 헤더 제목
#: 글자가 여기 해당한다. 크기·채움률로는 마커와 구별되지 않으므로 자리로만 갈린다.
DISTRACTORS = (((760.0, 118.0), (30, 18)), ((900.0, 2222.0), (24, 17)))
#: 띠 **안쪽**(좌 17% · 상 10%)에 든 덩어리 — 실물 all-059 에서 실제로 나온 자리다.
#: 띠를 좁혀서 떨구면 표본에 맞춘 튜닝이 되므로, 모서리 거리로 갈라야 한다.
INNER_DISTRACTOR = (((282.0, 232.0), (28, 18)),)


def synth_scan(angle=0.0, scale=1.0, noise=0, distractors=False, inner=False):
    """마커만 있는 합성 스캔. angle 은 도(度), 중심 회전."""
    width, height = SCAN_SIZE
    image = np.full((height, width), 255, dtype=np.uint8)
    blobs = MARKS + (DISTRACTORS if distractors else ()) + (INNER_DISTRACTOR if inner else ())
    for (cx, cy), (w, h) in blobs:
        x0, y0 = int(round(cx - w / 2)), int(round(cy - h / 2))
        image[y0 : y0 + h, x0 : x0 + w] = 20
    if angle or scale != 1.0:
        matrix = cv2.getRotationMatrix2D((width / 2, height / 2), angle, scale)
        image = cv2.warpAffine(
            image, matrix, (width, height), flags=cv2.INTER_LINEAR, borderValue=255
        )
    if noise:
        rng = np.random.default_rng(0)
        image = np.clip(
            image.astype(np.int16) + rng.integers(-noise, noise + 1, image.shape), 0, 255
        ).astype(np.uint8)
    return image


def expected_corners(angle=0.0, scale=1.0):
    """synth_scan 과 같은 변환을 CORNERS 에 적용한 기대 좌표."""
    width, height = SCAN_SIZE
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), angle, scale)
    points = np.hstack([CORNERS, np.ones((4, 1))])
    return points @ matrix.T


def test_finds_four_corner_marks_on_clean_scan():
    corners = normalize.find_corner_marks(synth_scan())

    assert corners is not None
    np.testing.assert_allclose(corners, CORNERS, atol=1.5)


def test_ignores_mark_sized_blobs_away_from_the_left_and_right_edges():
    """헤더 글자를 마커로 세면 후보가 4개를 넘어 장 전체가 보류로 떨어진다.

    실측에서 65장 중 39장이 이 이유로 실패했다(후보 5~8개) — 상·하단 띠만 걸러서
    가운데 글자가 통과했다. 마커는 네 **모서리**에 있으므로 좌우도 함께 걸러야 한다.
    """
    corners = normalize.find_corner_marks(synth_scan(distractors=True))

    assert corners is not None
    np.testing.assert_allclose(corners, CORNERS, atol=1.5)


def test_picks_the_marks_nearest_the_page_corners_when_a_fifth_blob_is_inside_the_band():
    """띠 안쪽 덩어리는 모서리에서 더 멀다 — 거리로 갈리지, 띠를 좁혀서 갈리지 않는다."""
    corners = normalize.find_corner_marks(synth_scan(inner=True))

    assert corners is not None
    np.testing.assert_allclose(corners, CORNERS, atol=1.5)


def test_orients_the_frame_to_the_cards_own_top_left():
    """정규좌표 (0,0) 은 스캔의 좌상단이 아니라 **카드의** 좌상단이다.

    카드가 눕는 방향을 코드에 박으면 급지가 뒤집힌 날 전부 조용히 어긋난다.
    긴 마커가 붙은 변이 카드의 위쪽이라는 사실로 매번 판별한다.
    """
    frame = normalize.locate_card(synth_scan())

    assert frame is not None
    mapped = [frame.to_source(u, v) for u, v in ((0, 0), (1, 0), (1, 1), (0, 1))]
    np.testing.assert_allclose(mapped, CORNERS[CARD_TO_SCAN], atol=1.5)


def test_maps_card_corners_back_onto_a_skewed_scan():
    """기울어도 카드 네 귀퉁이를 짚는다. -3.55° 는 실측 65장의 최대 기울기다."""
    angle = -3.55
    frame = normalize.locate_card(synth_scan(angle=angle))

    assert frame is not None
    mapped = [frame.to_source(u, v) for u, v in ((0, 0), (1, 0), (1, 1), (0, 1))]
    np.testing.assert_allclose(mapped, expected_corners(angle=angle)[CARD_TO_SCAN], atol=2)


def test_rejects_the_quad_when_a_stray_blob_stands_in_for_a_missing_marker():
    """마커가 하나 빠지고 그 모서리 띠 안에 마커 크기 잡티가 있으면 보류다.

    nearest 선택은 잡티를 그대로 물고 사각형은 겉보기에 멀쩡히 반환된다 — 실물
    재현에서 카드 중앙이 49px(선택지 한 칸 이상) 밀린 채 조용히 읽혔다. 그
    사각형은 기하가 실측 분포를 벗어나므로(대변비 1.146 대 실측 최대 1.0072,
    모서리각 이탈 11.1° 대 실측 최대 0.31°) 사각형 검증에서 걸린다.
    """
    image = synth_scan()
    (cx, cy), (w, h) = MARKS[0]  # 스캔 좌상 마커 유실(가림·인쇄 불량)
    image[int(cy - h) : int(cy + h), int(cx - w) : int(cx + w)] = 255
    image[224:241, 270:294] = 20  # 좌상 띠 안의 잡티 24x17 — all-059 의 자리다

    assert normalize.find_corner_marks(image) is None
    assert normalize.locate_card(image) is None


def test_accepts_the_worst_real_trapezoid():
    """실측 최악 기하는 통과한다 — 아래 변이 위 변보다 10px 넓은 사다리꼴.

    65장 실측에서 대변 길이비 최대 1.0072(약 10px), 모서리각 이탈 최대 0.31°.
    검증 한계(대변비 1.05 · 각 3°)는 그 최악값의 6~10배 밖이다.
    """
    wide_bottom = (
        ((115.0, 120.0), (21, 18)),
        ((1525.0, 120.0), (36, 18)),
        ((1530.0, 2225.0), (36, 18)),
        ((110.0, 2225.0), (21, 18)),
    )
    width, height = SCAN_SIZE
    image = np.full((height, width), 255, dtype=np.uint8)
    for (cx, cy), (w, h) in wide_bottom:
        x0, y0 = int(round(cx - w / 2)), int(round(cy - h / 2))
        image[y0 : y0 + h, x0 : x0 + w] = 20

    corners = normalize.find_corner_marks(image)

    assert corners is not None
    np.testing.assert_allclose(corners, [c for c, _ in wide_bottom], atol=1.5)

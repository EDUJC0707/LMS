"""판형 — 카드 위 셀이 어디에 있나. **이미지를 모른다. 순수 데이터다**(PRD 3.1.1).

판형이 바뀌면 **이 파일만** 갈아 끼운다. 읽는 코드(read)도 해석하는 코드(decode)도
그대로다. 카드는 앞으로 통일된다(decisions.md §5)므로 판형별 분기는 두지 않는다 —
한 벌만 두고 값을 바꾼다.

## 값의 출처

빈 카드 실물(`local/sources/basis/omr/test-omr-blank.pdf`)을 200dpi 로 렌더한
2339x1654 이미지에서 잰 픽셀 좌표다(2026-08-04). **재 온 단위 그대로 적고 정규화는
코드가 한다** — 손으로 환산해 적으면 열두 개 중 하나가 틀려도 아무도 못 찾는다.

정규좌표는 `normalize.CardFrame` 과 같은 축이다: (0,0) 카드 좌상 마커, (1,1) 우하
마커. 카드 위 자리를 "마커 간격의 몇 분의 몇"으로 적으면 스캔의 배율·기울기·
사다리꼴이 전부 변환에 흡수된다.

## 검산

버블 총수 328 = 성명 188 + 전화 40 + 답란 100. 빈 카드에서 링을 세었을 때
정확히 이 수가 나왔다. 값이 어긋나면 이 수부터 깨지므로 테스트가 먼저 잡는다.
"""

# --- 실측 기준 프레임 (빈 카드 200dpi 렌더의 마커 중심) ---------------------
BLANK_MARK_X = (56.5, 2280.0)
BLANK_MARK_Y = (88.5, 1582.0)

# --- 답란: 20문항 × 5지선다 -------------------------------------------------
#: 선택지 ①~⑤ 의 열 중심 x. 간격이 41px 로 균일하지만 잰 값을 그대로 둔다.
ANSWER_CHOICE_X = (1214.0, 1255.0, 1296.0, 1337.0, 1378.0)
#: 1번 행과 20번 행의 중심 y. 사이는 균등 분할(실측 행간격 65px).
ANSWER_ROW_Y = (241.0, 1467.0)
ANSWER_QUESTIONS = 20
ANSWER_CHOICES = 5

#: 실물 스캔 65장으로 맞춘 보정량(정규좌표). 빈 카드 PDF 에서 잰 좌표를 그대로
#: 쓰면 셀 중심이 버블 링 위에 걸친다 — 빈 카드 x 로 +4.9px, y 로 -2.1px 만큼.
#:
#: 65장을 정규좌표에서 평균 내면 학생 마킹은 씻겨 나가고 인쇄 격자만 남는다.
#: 그 평균판에서 버블 안쪽 잉크가 최대가 되는 자리를 찾아 얻은 값이다.
#: **반 피치 미만으로 묶어서 찾는다** — 안 묶으면 한 칸 통째로 건너뛴 자리가
#: 더 높은 점수를 받는다(빈 줄이 블록 테두리에 얹혀 잉크가 커진다).
#: 값이 작은 이유는 빈 카드가 다른 회차(`OMEGA black 3회`)라 내용 배치가
#: 미세하게 다르고, 링 검출 중심에도 치우침이 있기 때문이다.
CALIBRATION_U = 0.00220
CALIBRATION_V = -0.00143


def answer_cells():
    """답란 100칸 — `((문항번호, 선택지), (u, v))` 목록. 문항·선택지는 1부터."""
    us = [_u(x) + CALIBRATION_U for x in ANSWER_CHOICE_X]
    vs = [v + CALIBRATION_V for v in _even_rows(ANSWER_ROW_Y, ANSWER_QUESTIONS)]
    return [
        ((question, choice), (us[choice - 1], vs[question - 1]))
        for question in range(1, ANSWER_QUESTIONS + 1)
        for choice in range(1, ANSWER_CHOICES + 1)
    ]


# --- 내부 부품 --------------------------------------------------------------


def _u(x):
    """빈 카드 픽셀 x → 정규좌표 u."""
    left, right = BLANK_MARK_X
    return (x - left) / (right - left)


def _v(y):
    """빈 카드 픽셀 y → 정규좌표 v."""
    top, bottom = BLANK_MARK_Y
    return (y - top) / (bottom - top)


def _even_rows(span, count):
    """첫 행·끝 행 중심 사이를 균등 분할한 정규좌표 목록.

    행마다 중심을 다 적지 않는 이유는 잰 값이 등간격이었기 때문이다 — 스무 개를
    적어 두면 그중 하나가 틀려도 눈에 안 띈다.
    """
    first, last = span
    step = (last - first) / (count - 1)
    return [_v(first + step * index) for index in range(count)]

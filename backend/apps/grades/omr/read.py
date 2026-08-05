"""셀 농도 → 무엇이 칠해졌나. **그 마킹이 정답인지는 모른다**(PRD 3.1.1).

정답 대조는 채점의 몫이고 여기는 "지면에 무엇이 있나"까지만 답한다.

## 왜 절대 임계를 쓰지 않나

실물 65장(1040문항) 측정에서 절대 임계는 37문항을 판정 불가로 남겼다. 원인이 둘이다:

- **인쇄 글리프**: 빈칸에도 ①~⑤ 가 인쇄돼 있어 잉크가 남는다. 칸마다 양이
  달라 빈칸 기준선이 31.6(①) ~ 47.0(⑤) 으로 갈린다
- **연필 압력**: 장별 중앙 lead 가 48.8 ~ 154.5 로 3배 차이 난다. 흐리게 쓰는
  학생의 정상 마킹이 진하게 쓰는 학생의 얼룩보다 옅다

그래서 판정을 두 번 상대화한다. **줄 안에서** 나머지 넷을 기준선으로 삼고,
그 lead 를 **그 장의** 전형적인 lead 와 견준다. 그러면 글리프 차이도 압력
차이도 함께 나눠 없어진다.

## 임계값의 근거

- `LEAD_FRACTION = 0.25` — 장 중앙 lead 의 25% 미만이면 빈칸으로 본다.
  **옛 0.40 과 "0.35~0.50 고원"은 최근접 표본계의 산물이었다.** 쌍선형 11x11 로
  바꾸니 부분 마킹의 참값이 드러나 고원이 **0.20~0.35** 로 옮겨갔고, 0.40 에서는
  칸을 벗어나게 칠한 실제 답 2건이 죽는다(1027/4/9). 0.25 는 새 고원 안이다
- 복수 마킹 문턱은 `min(RUNNER_MIN, RUNNER_FRACTION x 장 중앙 lead)` 다.
  절대값 하나만 쓰면 문턱이 장에 따라 중앙 lead 의 0.32배(중앙 154)에서
  1.03배(중앙 48.5)까지 벌어진다 — **감도가 3.18배 갈린다.** 실물 X 넷의 2등은
  중앙 lead 의 0.93~1.17배였으므로, 같은 X 를 제일 흐린 장에 옮기면 2등이 ~45 로
  절대 50 아래에 숨어 **단일 확신 판정으로 나간다.** 그래서 문턱도 장에 맞춰 내린다
- `RUNNER_FRACTION = 0.65` — 상대 공간에서 잡음 천장이 0.468(인쇄 ⑤ 글리프),
  신호 바닥이 0.926(X)이라 1.98배 벌어져 있다. 0.65 는 그 기하 중점이다
- `RUNNER_MIN = 50.0` 은 **하한으로 남긴다.** 상대만 쓰면 진한 장(중앙 154)에서
  문턱이 100 까지 올라가 절대 85 짜리 X 를 놓친다. 비-X 전수의 2등 최대가 34.8 이라
  이 하한이 만드는 오탐은 0 — 재현율만 얻고 잃는 게 없다. 하한을 두면 고원이
  0.47~1.40 으로 넓어진다(상대 단독은 0.47~0.92)

이 규칙으로 1040문항이 단일 1029 · 복수 4 · 빈칸 7 로 갈렸고, 복수 넷은 눈으로
찾은 X 넷과, 빈칸 일곱은 절대 농도로 찾은 빈칸 일곱과 정확히 일치했다.
"""
from statistics import median

import numpy as np

#: 장 중앙 lead 대비 이 비율 미만이면 빈칸 — 모듈 docstring 참조.
LEAD_FRACTION = 0.25
#: 2등이 줄 기준선보다 이만큼 위면 복수 마킹 — **절대 하한**. 상대 문턱과 함께 쓴다.
RUNNER_MIN = 50.0
#: 2등이 장 중앙 lead 의 이 비율을 넘어도 복수 마킹 — 흐린 장을 위한 눈금.
RUNNER_FRACTION = 0.65
#: 연필이 닿았다고 볼 수 있는 lead 하한 — 개별 판정용이 아니라 **집계용**이다.
#: 실물 빈칸 267줄의 lead 최대가 32.5 인데 실제 마킹 1033줄의 최소는 29.5 라
#: 겹친다 — 그래서 이 값으로 문항 하나를 판정하지 않는다. 줄 수를 세는 데만 쓴다:
#: 잡음은 40 을 못 넘고, 실물 65장 전부가 40 이상인 줄을 13줄 넘게 가진다.
PENCIL_LEAD_MIN = 40.0
#: 확실히 빈칸인 절대 상한 / 확실히 마킹인 절대 하한.
#: **쌍선형 표본계에서 두 모집단이 갈라졌다** — 실측(65장, 진짜 빈 줄 267 · 마킹
#: 1033): 빈칸 최대 **11.7**, 마킹 최소 **42.6**. 최근접 표본계에서 29.5 대 32.5 로
#: 겹쳐 보였던 것은 양자화 잡음이었다("절대값으로는 원리상 못 가른다"는 옛 결론은
#: 표본계의 산물이지 지면의 성질이 아니었다). 20 과 35 는 그 30 눈금짜리 빈
#: 구간 안이고, 아래로 1.7배 · 위로 1.2배 여유가 있다.
BLANK_MAX_ABS = 20.0
MARK_MIN_ABS = 35.0
#: 빈칸이라고 확신할 수 있는 상한(장 중앙 lead 대비). 이 위 ~ 마킹 문턱 사이는
#: **어느 쪽도 아니다** — 접힘·잘림으로 희석된 마킹이 정확히 거기 떨어진다.
#: 실측: 빈칸 비 최대 0.094 · 마킹 비 최소 0.342 로 그 사이가 통째로 비어 있다.
#: 그 구간에 든 줄이 하나라도 있으면 **장째 보류**한다 — 희석된 마킹을 조용히
#: "무응답"으로 채점하는 것이 이 엔진의 마지막 사각지대였다.
BLANK_MAX_RATIO = 0.15
#: 표본 자리가 인쇄 격자 위라고 믿기 위한 절대 바닥. 줄 기준선은 인쇄 글리프가
#: 있어 실물 1300줄 전부 24.5 이상이었다 — 맨 종이는 0~5 다. 이 아래면 격자가
#: 지면을 벗어난 것이고(접힘·뒤틀림), 그 장의 모든 좌표를 못 믿는다.
MIN_ROW_FLOOR = 12.0
#: 버블 반지름의 몇 할까지만 표본할지. 링에 물리면 빈칸이 칠한 것처럼 읽힌다 —
#: 실제로 보정 전 격자가 링에 얹혔을 때 그 일이 났다.
INTERIOR_FRACTION = 0.65
#: 표본점 격자 — 안쪽 타원에 드는 점만 쓴다(11x11 중 77점).
#: 7x7(29점)은 정답을 낼 수 있는 **최소** 밀도였고, 그때 INTERIOR_FRACTION 이
#: 통하는 대역은 0.65~0.70 두 칸뿐이었다(9x9 는 0.7·0.9 에서 도로 깨진다 —
#: 비단조성 자체가 양자화 잡음의 징후다). 11x11 은 0.6~1.0 전 대역에서 안정하다.
_SAMPLE_STEPS = 11


def sample_cells(image, frame, cells, radius):
    """`{셀 키: 잉크 0~255}` — 클수록 진하다.

    **이미지를 통째로 펴지 않는다.** 셀마다 정규좌표를 원본 픽셀로 되짚어 그
    자리만 읽는다. 전체 워프는 리샘플링으로 농도를 뭉개는데, 우리가 재려는 것이
    바로 그 농도다.

    (셀 × 표본점) 좌표를 한 번에 변환하고 픽셀도 한 번에 모은다 — 점마다 돌던
    순수 파이썬 루프가 장당 9.6ms 로 파이프라인의 절반이었다(실물 65장 실측,
    벡터화로 83배). 값은 루프판과 비트 단위로 같다 — test_read 가 고정한다.
    """
    height, width = image.shape
    if not cells:
        return {}
    offsets = _interior_offsets(radius)
    keys = [key for key, _ in cells]
    centers = np.array([center for _, center in cells], dtype=np.float64)
    totals = np.zeros(len(keys), dtype=np.float64)
    for offset in offsets:
        xs, ys = frame.to_source_many(centers + offset)
        columns = np.clip(np.floor(xs).astype(np.intp), 0, width - 2)
        rows = np.clip(np.floor(ys).astype(np.intp), 0, height - 2)
        fx = np.clip(xs - columns, 0.0, 1.0)
        fy = np.clip(ys - rows, 0.0, 1.0)
        totals += (
            (1 - fx) * (1 - fy) * image[rows, columns]
            + fx * (1 - fy) * image[rows, columns + 1]
            + (1 - fx) * fy * image[rows + 1, columns]
            + fx * fy * image[rows + 1, columns + 1]
        )
    inks = 255.0 - totals / len(offsets)
    return dict(zip(keys, inks))


def _interior_offsets(radius):
    """버블 안쪽 타원에 고르게 뿌린 표본 오프셋."""
    radius_u, radius_v = (value * INTERIOR_FRACTION for value in radius)
    steps = np.linspace(-1.0, 1.0, _SAMPLE_STEPS)
    return [
        (radius_u * a, radius_v * b)
        for a in steps
        for b in steps
        if a * a + b * b <= 1.0
    ]


def classify_answers(inks):
    """`{문항: {선택지: 잉크}}` → `{문항: (칠해진 선택지, ...)}`.

    빈 튜플은 빈칸이다. 둘 이상이면 복수 마킹 — 어느 쪽이 진짜인지는 정하지
    않는다(X 로 지운 것인지 겹쳐 칠한 것인지 기계가 못 가른다. PRD 3.1.1 의
    마킹 이상 경고로 넘어가 사람이 본다).

    **None 은 장 전체 보류다.** 연필이 닿은 줄이 절반 이하면 lead 중앙값이 연필
    통계가 아니라 인쇄 잡음 통계다 — 그 40% 를 빈칸 기준으로 삼으면 빈 줄의 글리프
    잡음이 답으로 승격된다(실측: 빈 장을 넣으면 65장 전원이 12~16문항을 답으로
    읽었고, 고른 선택지는 글리프 잉크가 무거운 순서였다). 잡음과 흐린 마킹은
    절대값으로 안 갈리므로(마킹 최소 29.5 < 잡음 최대 32.5) 몇 줄만 골라 살리지
    않고 장째 사람에게 넘긴다 — 방향을 못 가릴 때 보류하는 locate_card 와 같은 태도다.
    """
    if not inks:
        return {}
    column_floors = _column_floors(inks)
    rows = {
        question: _row_stats(cells, column_floors) for question, cells in inks.items()
    }
    leads = [stats.lead for stats in rows.values()]
    if 2 * sum(lead >= PENCIL_LEAD_MIN for lead in leads) <= len(leads):
        return None
    if min(stats.floor for stats in rows.values()) < MIN_ROW_FLOOR:
        return None
    sheet_lead = median(leads)
    floor_lead = max(LEAD_FRACTION * sheet_lead, MARK_MIN_ABS)
    blank_ceiling = max(BLANK_MAX_RATIO * sheet_lead, BLANK_MAX_ABS)
    if any(blank_ceiling <= stats.lead < floor_lead for stats in rows.values()):
        return None
    runner_min = min(RUNNER_MIN, RUNNER_FRACTION * sheet_lead)
    return {
        question: _marked_choices(stats, floor_lead, runner_min)
        for question, stats in rows.items()
    }


class _RowStats:
    """한 문항 다섯 칸의 상대값 — 기준선과 그 위 높이들."""

    __slots__ = ("floor", "lead", "heights", "top")

    def __init__(self, floor, lead, heights, top):
        self.floor = floor
        self.lead = lead
        self.heights = heights
        self.top = top


def _column_floors(inks):
    """선택지별 잉크 중앙값 — 그 열의 "안 칠한 값"이다.

    줄 기준선은 글리프가 무거운 칸(⑤ 47.0)과 가벼운 칸(① 31.6)을 한 값으로 뭉갠다 —
    가벼운 칸 위의 마킹은 높이가 약 15 깎인다. 열 중앙값은 그 차이를 그대로 담는다.
    한 열이 문항 절반 넘게 칠해지면 이 중앙값도 오염되지만, 그때는 줄 기준선이
    살아 있으므로 min 이 막는다.
    """
    return {
        choice: median(cells[choice] for cells in inks.values())
        for choice in next(iter(inks.values()))
    }


def _row_stats(cells, column_floors):
    """칸의 기준선 = min(줄의 나머지 넷 중앙값, 그 열의 장 중앙값).

    줄 기준선 하나만 쓰면 두 방향으로 깨진다(실측):

    - **세 칸을 칠하면** "나머지 넷"에 마킹이 둘 들어와 기준선이 마킹 높이의 절반까지
      올라간다 — 높이가 반토막 나 셋 중 **하나만** 확신 단일로 나간다(장 중앙 lead
      100 미만, 코퍼스의 25%). **넉 칸이면 기준선이 마킹 그 자체**가 되어 전 장에서
      **빈칸**으로 나간다 — 학생이 넷을 칠했는데 "무응답"이 된다
    - **글리프가 가벼운 칸**(①·④)의 마킹은 높이가 약 15 깎여, 제일 흐린 장에서는
      진짜 X 취소 흔적이 복수 문턱 밑으로 숨는다

    열 중앙값은 줄 안의 마킹 수와 무관하고, 줄 중앙값은 열 안의 마킹 수와 무관하다 —
    min 은 둘 중 오염되지 않은 쪽을 고른다.
    """
    row_floor = median(sorted(cells.values())[:4])
    heights = {
        choice: ink - min(row_floor, column_floors[choice])
        for choice, ink in cells.items()
    }
    top_choice = max(heights, key=heights.get)
    return _RowStats(row_floor, heights[top_choice], heights, top_choice)


def _marked_choices(stats, floor_lead, runner_min):
    """기준을 넘긴 칸들. 1등은 기준을 넘겼다면 항상 들어간다."""
    if stats.lead < floor_lead:
        return ()
    marked = {choice for choice, height in stats.heights.items() if height >= runner_min}
    marked.add(stats.top)
    return tuple(sorted(marked))

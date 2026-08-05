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

- `LEAD_FRACTION = 0.40` — 장 중앙 lead 의 40% 미만이면 빈칸으로 본다.
  0.35~0.50 구간에서 결과가 동일했다(1029/4/7 고정) — 고원 한가운데 값이다
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
LEAD_FRACTION = 0.40
#: 2등이 줄 기준선보다 이만큼 위면 복수 마킹 — **절대 하한**. 상대 문턱과 함께 쓴다.
RUNNER_MIN = 50.0
#: 2등이 장 중앙 lead 의 이 비율을 넘어도 복수 마킹 — 흐린 장을 위한 눈금.
RUNNER_FRACTION = 0.65
#: 버블 반지름의 몇 할까지만 표본할지. 링에 물리면 빈칸이 칠한 것처럼 읽힌다 —
#: 실제로 보정 전 격자가 링에 얹혔을 때 그 일이 났다.
INTERIOR_FRACTION = 0.65
#: 표본점 격자 — 안쪽 타원에 드는 점만 쓴다(7x7 중 29점).
_SAMPLE_STEPS = 7


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
    offsets = np.array(_interior_offsets(radius), dtype=np.float64)
    keys = [key for key, _ in cells]
    centers = np.array([center for _, center in cells], dtype=np.float64)
    points = (centers[:, None, :] + offsets[None, :, :]).reshape(-1, 2)
    xs, ys = frame.to_source_many(points)
    columns = np.clip(np.rint(xs).astype(np.intp), 0, width - 1)
    rows = np.clip(np.rint(ys).astype(np.intp), 0, height - 1)
    samples = image[rows, columns].reshape(len(keys), -1)
    inks = 255.0 - samples.sum(axis=1, dtype=np.float64) / len(offsets)
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
    """
    rows = {question: _row_stats(cells) for question, cells in inks.items()}
    if not rows:
        return {}
    sheet_lead = median(stats.lead for stats in rows.values())
    floor_lead = LEAD_FRACTION * sheet_lead
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


def _row_stats(cells):
    """나머지 넷의 중앙값을 기준선으로 삼는다 — 칠해진 칸 하나가 기준선을 끌어올리지 못한다."""
    ordered = sorted(cells.items(), key=lambda item: item[1], reverse=True)
    top_choice = ordered[0][0]
    floor = median(ink for _, ink in ordered[1:])
    heights = {choice: ink - floor for choice, ink in cells.items()}
    return _RowStats(floor, heights[top_choice], heights, top_choice)


def _marked_choices(stats, floor_lead, runner_min):
    """기준을 넘긴 칸들. 1등은 기준을 넘겼다면 항상 들어간다."""
    if stats.lead < floor_lead:
        return ()
    marked = {choice for choice, height in stats.heights.items() if height >= runner_min}
    marked.add(stats.top)
    return tuple(sorted(marked))

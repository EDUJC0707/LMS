"""판형 막대 읽기 — **카드 프레임 위에서** 돈다.

## 왜 프레임 위인가

예전에는 스캔 원본을 직접 훑었다. 머리말에 이유가 이렇게 적혀 있었다 —
"셀을 표본하려면 판형을 알아야 하고, 판형을 알려면 지면을 읽어야 한다".
**그 순환은 없다.** `normalize.locate_card` 는 판형을 몰라도 된다: 네 모서리
마커는 판형과 무관하게 같고, 위아래 크기 차이로 방향까지 그 안에서 가려낸다.

그 전제를 믿고 원본을 훑은 대가는 컸다. 원본 훑기는 "막대는 세로로 길고 좌우
끝에 있다"를 못으로 박아야 하는데, **실제 스캔은 세로로 들어온다**(A4 를 짧은
변부터 먹이므로 카드가 90° 누운 채 들어온다). 그러면 막대가 가로로 눕고 위아래
변에 붙어 종횡비·가장자리 필터가 하나도 안 걸린다 — 세 판형 전부 `None` 이었다.

프레임 위에서는 배율·평행이동·회전·사다리꼴을 **프레임이 이미 흡수**하므로
슬롯 자리를 그냥 짚으면 된다. 가장자리 띠·종횡비·높이비·앵커 역산·슬롯
허용오차가 전부 필요 없어졌다.

## 어떻게 어긋남을 견디나

- **좌우를 따로 읽는다.** 한쪽 가장자리가 스캔에서 날아가도 반대쪽으로 읽힌다
- **둘이 다르면 안 읽는다.** 조용히 틀리느니 보류가 낫다(`decode_bars` 의
  앵커·패리티도 같은 축)
- **대비가 없으면 안 읽는다.** 막대가 아예 없는 지면에서 잡음으로 8비트를
  지어내지 않게, 변 안의 최대·최소 차가 `MIN_CONTRAST` 를 넘어야 판정한다

## 한계

막대가 없으면 `None` 이다 — 옛 튜터시스템 카드가 그렇고, 그쪽은 종전대로
`exams.kind` 로 판형을 정한다.
"""
from decimal import Decimal

from . import layout as L
from .read import sample_cells

#: 막대 한가운데만 짚는다. 막대는 1.10 x 7.62mm 이므로 가로는 그 3분의 2,
#: 세로는 3분의 1 만 본다 — 가장자리를 물면 사다리꼴 잔차에 흔들린다.
SAMPLE_RU = float(L.mm_to_u(Decimal("0.35")))
SAMPLE_RV = float(L.mm_to_v(Decimal("2.4")))
#: 한 변에서 이만큼은 차이가 나야 "찍힌 것과 안 찍힌 것"을 갈랐다고 본다.
#: 막대는 검정 실칠이라 깨끗한 스캔에서 255 가 나온다. 빈 지면은 0 에 붙는다.
MIN_CONTRAST = 60.0

#: 막대 자리에 인쇄가 아예 없다 — 옛 튜터시스템 카드다.
#:
#: **`None` 과 갈라야 한다.** 둘을 뭉치면 우리 카드인데 막대를 못 읽은 장이
#: 조용히 옛 좌표로 읽혀 답이 통째로 밀린다. 없으면 옛 카드로 넘기고, 있는데
#: 못 읽으면 보류다.
ABSENT = "막대 없음"

SIDES = (0, 1)


def bar_cells():
    """{(변, 슬롯): (u, v)} — 마커 기준 자리. **판형과 무관한 상수뿐이다.**

    그래서 판형을 모르는 채로도 짚을 수 있고, 순환이 생기지 않는다.
    """
    return [
        ((side, slot),
         (float(side),
          float(L.mm_to_v(L.BAR_TOP_MM + slot * L.BAR_PITCH_MM - L.MARK_Y_MM[0]))))
        for side in SIDES
        for slot in range(L.BAR_SLOTS)
    ]


def _read_side(ink):
    """한 변의 슬롯별 잉크 -> 판형 id · ABSENT · None(있는데 못 읽음)."""
    values = list(ink.values())
    low, high = min(values), max(values)
    if high - low < MIN_CONTRAST:
        return ABSENT
    floor = (low + high) / 2
    return L.decode_bars(tuple(ink[slot] > floor for slot in range(L.BAR_SLOTS)))


def read_layout(image, frame):
    """스캔 + 카드 프레임 -> 판형 id · `ABSENT` · None.

    좌우를 따로 읽는다:

    - 둘 다 판형을 말하는데 **다르면 None** — 한쪽이 오염됐다는 뜻이라 어느
      쪽을 믿을지 알 수 없다. 조용히 틀리느니 보류다
    - 한쪽만 읽히면 그쪽을 쓴다. 스캔에서 가장자리가 날아가는 일이 있다
    - 둘 다 비어 있으면 `ABSENT` — 옛 카드다
    - 한쪽이 비고 한쪽이 못 읽었으면 None. 막대가 있는 지면이라는 뜻이므로
      옛 카드로 넘기면 안 된다
    """
    ink = sample_cells(image, frame, bar_cells(), (SAMPLE_RU, SAMPLE_RV))
    left, right = (
        _read_side({slot: ink[(side, slot)] for slot in range(L.BAR_SLOTS)})
        for side in SIDES
    )
    ids = [side for side in (left, right) if side not in (ABSENT, None)]
    if ids:
        return ids[0] if len(ids) == 1 or ids[0] == ids[1] else None
    return ABSENT if left is ABSENT and right is ABSENT else None

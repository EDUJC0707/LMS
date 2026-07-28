#!/usr/bin/env python3
"""히어로 모티프 배치 계산.

**크기는 전부 같다. 겹치지 않는다. 뷰포트 안에 다 들어간다.**
그 셋을 지키면서 최대 크기를 찾는 것이 이 스크립트의 전부다.

다만 균등 난수로 뿌리면 안 된다 — 고르게 흩어진 배치는 무작위인데도 평평하고
투박하게 읽힌다. 크기로는 리듬을 만들 수 없으므로(다 같으니까) 리듬은 두 군데서만
나온다.

1. 자리 — 빈 공간을 격자로 쪼개 여유 있는 칸만 존으로 쓰고, 존마다 하나씩 배정한
   뒤 그 안에서 흔든다. 구도는 통제되고 리듬은 살아난다.
2. 회전 — 난수로 뽑으면 뭉친다(실측: 10개 중 5개가 16~17°). 각도를 사다리로 깔고
   섞어 좌우 균형과 분산을 강제하고, 0° 근처는 아예 비운다.

충돌 판정은 경계상자가 아니라 **회전 후 잉크 마스크**로 한다. DNA 처럼 성긴 그림은
경계상자로 재면 면적의 77% 를 헛되이 버린다.

  python3 pack-layout.py            # 데스크탑 1440x900
  python3 pack-layout.py --mobile   # 390x844
"""
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
MOTIFS = HERE / "assets" / "motifs"
NAMES = ["atom", "dna", "chromosome", "mitochondria", "chloroplast", "synapse",
         "population", "element", "tectonics", "universe"]

MOBILE = "--mobile" in sys.argv
VW, VH = (390, 844) if MOBILE else (1440, 900)
CELL = 4
NAV = 64
# 잉크 사이 최소 여백. **런타임 상대 이동을 여기서 덮는다** — field.js 가 개체마다
# 위상이 다른 자율 부유(±6px)를 주므로 이웃 둘이 서로에게 최대 12px 다가온다.
# 시차는 전원이 같은 방향이라 상대 거리를 바꾸지 않는다. 12px + 여유 = 24.
GAP = 18 if MOBILE else 24
# 가장자리 여유. field.js 가 런타임에 개체를 최대 ±15px 흔들기 때문에(시차 8px +
# 자율부유 6px) 여기서 그만큼을 미리 빼둬야 한다. 10px 로 두면 왼쪽·위가 잘렸다.
EDGE = 30
# 기울기는 난수로 뽑지 않는다. 뽑아 보니 10개 중 5개가 16~17°에 몰려 **전부 같은
# 방향으로 기운 정렬**이 됐다 — 무작위는 뭉치기 때문이다. 그래서 각도를 사다리로
# 깔고 섞는다: 좌우 균형이 보장되고, 0° 근처(스티커처럼 보이는 각)가 비어 있다.
TILT_SET = [-33, -26, -19, -12, -7, 7, 12, 19, 26, 33]
TILT_JIT = 3                          # 사다리 위 미세 흔들기 — 등차 티를 지운다
NO_ALIGN = 3.0                        # 중심이 x·y 둘 다 이만큼 가까우면 거부

# 크기는 전부 같다(사용자 지시 2026-07-28: "크기는 같게 겹치지는 않게").
# 크기로 리듬을 만들지 않으므로 불규칙성은 **회전과 자리**에서만 나온다.
# 한때 크기 사다리를 썼지만 되돌렸다 — 기록만 남기고 값은 균일하다.
SIZE_EQ = 1.0
JITTER = 0.0

# 텍스트 뒤는 지나가도 된다(사용자 지시 2026-07-28) — 톤 위계가 잡혀 있어
# 배경(피크 휘도 68)이 헤드라인(110)보다 어둡기 때문이다. 대신 강사는 금지다.
TEACHER = HERE / "assets" / "teacher" / "nobg" / "02-검정티-턱손.webp"
TEACHER_H = 0.40 if MOBILE else 0.80      # index.html .teacher height
TEACHER_RIGHT = -0.12 if MOBILE else 0.05  # index.html .teacher right
TEACHER_PAD = 26          # 인물 실루엣 주변 여유(px)

GW, GH = VW // CELL, VH // CELL
rng = np.random.default_rng(20260728)

# 임계값을 12 로 낮춰 **실제 렌더보다 넓게** 잡는다. 화면에서는 CSS mask-image 가
# 실루엣 최외곽을 한 번 더 깎으므로, 여기서 넉넉히 잡으면 항상 안전한 쪽으로 틀린다.
MASKS = {n: (np.array(Image.open(MOTIFS / f"{n}.webp").convert("RGBA").split()[3]) > 12)
         for n in NAMES}


def stamp(n, size_px, deg):
    """회전·축소한 잉크 마스크 + 여백 팽창."""
    img = Image.fromarray(MASKS[n].astype(np.uint8) * 255)
    if deg:
        img = img.rotate(deg, resample=Image.BILINEAR, expand=True, fillcolor=0)
    g = max(4, size_px // CELL)
    m = np.array(img.resize((g, g), Image.BILINEAR)) > 90
    pad = max(1, GAP // CELL)
    out = np.zeros_like(m)
    for dy in range(-pad, pad + 1):
        for dx in range(-pad, pad + 1):
            if dx * dx + dy * dy > pad * pad:
                continue
            out |= np.roll(np.roll(m, dy, 0), dx, 1)
    return out


def forbidden():
    """nav · 화면 가장자리 · 강사와 그 오른쪽 전부. 헤드라인은 막지 않는다."""
    f = np.zeros((GH, GW), bool)
    f[: (NAV + 6) // CELL, :] = True
    e = max(1, EDGE // CELL)
    f[:e, :] = f[-e:, :] = True
    f[:, :e] = f[:, -e:] = True

    # 강사 왼쪽에 **전 높이 하드 라인**을 긋는다(사용자 지시 2026-07-28:
    # "선생님 뒤에, 오른쪽에 안된다니깐 그냥 hard line where 선생님 starts").
    # 인물의 세로 구간만 막았더니 모바일에서 상단 우측이 열려 모티프가 인물 위쪽
    # 공중에 떴다. 세로를 나누지 않고 한 줄로 자른다 — 경계가 명확해야 한다.
    ti = Image.open(TEACHER)
    th = min(TEACHER_H * VH, 820)
    tw = th * ti.width / ti.height
    left = VW - TEACHER_RIGHT * VW - tw - TEACHER_PAD
    f[:, max(0, int(left // CELL)):] = True
    return f, left


FORBID, TEACHER_LEFT = forbidden()
_free = (~FORBID).mean()
print(f"// 강사 왼쪽 경계 {TEACHER_LEFT / VW * 100:.0f}% · 사용 가능 면적 {_free * 100:.0f}%")




# 구도를 먼저 정한다. 순수 난수는 고르게 흩어져 평평하고, 군집 선호만 주면 한쪽으로
# 쏠린다. 그래서 빈 공간을 격자로 쪼개 여유가 있는 칸만 존으로 쓰고, 존마다 하나씩
# 배정한 뒤 그 안에서 흔든다 — 구도는 통제되고 리듬은 살아난다.
# 존을 손으로 적으면 금지구역이 바뀔 때마다 어긋나므로 FORBID 에서 뽑는다.
def make_zones(cols, rows, need):
    cw, ch = GW / cols, GH / rows
    cand = []
    for j in range(rows):
        for i in range(cols):
            x0, x1 = int(i * cw), int((i + 1) * cw)
            y0, y1 = int(j * ch), int((j + 1) * ch)
            free = (~FORBID[y0:y1, x0:x1]).mean()
            if free < 0.45:
                continue
            # 칸 안쪽으로 조금 물려 존 경계에 딱 붙지 않게 한다
            mx, my = (x1 - x0) * 0.08, (y1 - y0) * 0.08
            cand.append((free, ((x0 + mx) * CELL / VW * 100, (x1 - mx) * CELL / VW * 100,
                                (y0 + my) * CELL / VH * 100, (y1 - my) * CELL / VH * 100)))
    cand.sort(key=lambda z: -z[0])
    return [z for _, z in cand[:max(need, len(cand))]]


ZONES = None
for cols, rows in ((4, 3), (5, 4), (6, 4), (5, 5), (6, 5), (7, 5)):
    z = make_zones(cols, rows, len(NAMES))
    if len(z) >= len(NAMES):
        ZONES = z
        print(f"// 존 {cols}x{rows} 격자에서 {len(z)}칸 확보")
        break
if ZONES is None:
    sys.exit("존 확보 실패 — 금지구역이 너무 넓다")


def attempt(scale, seed):
    """존마다 하나씩 배정하고 그 안에서 자리를 찾는다."""
    r = np.random.default_rng(seed)
    zones = list(ZONES)
    if len(zones) < len(NAMES):
        return None
    r.shuffle(zones)
    order = list(NAMES)
    r.shuffle(order)

    # 크기가 같으므로 순서에 유불리가 없다. 다만 잉크가 넓은 것(chromosome 32%,
    # element)이 뒤로 밀리면 자리가 없으므로 **잉크 면적이 큰 것부터** 놓는다.
    tilts = list(TILT_SET[:len(order)])
    r.shuffle(tilts)
    plan = sorted(zip(order, zones, tilts), key=lambda p: -MASKS[p[0]].mean())

    occ = FORBID.copy()
    placed, centers = {}, []

    for n, (zx1, zx2, zy1, zy2), base_deg in plan:
        size_px = int(VW * scale / 100 * SIZE_EQ)
        deg = float(base_deg + r.uniform(-TILT_JIT, TILT_JIT))
        m = stamp(n, size_px, deg)
        gh, gw = m.shape
        if gh >= GH or gw >= GW:
            return None
        ok = False
        for _ in range(1600):
            cx = r.uniform(zx1, zx2)
            cy = r.uniform(zy1, zy2)
            gx = int(cx / 100 * VW / CELL - gw / 2)
            gy = int(cy / 100 * VH / CELL - gh / 2)
            if gx < 0 or gy < 0 or gx + gw >= GW or gy + gh >= GH:
                continue
            if (occ[gy:gy + gh, gx:gx + gw] & m).any():
                continue
            # 정렬 금지 — 다만 'x 또는 y'로 걸면 가로가 좁을 때 아예 배치가 불가능해진다.
            # 좌표가 둘 다 가까운 경우(사실상 중복)만 거부하고, 격자스러움은 존 안
            # 흔들기로 깬다.
            if any(abs(cx - px) < NO_ALIGN and abs(cy - py) < NO_ALIGN for px, py in centers):
                continue
            occ[gy:gy + gh, gx:gx + gw] |= m
            placed[n] = (gx, gy, gw, gh, size_px, deg)
            centers.append((cx, cy))
            ok = True
            break
        if not ok:
            return None
    return placed


best = None
lo, hi = 4.0, 50.0
for _ in range(20):
    mid = (lo + hi) / 2
    got = None
    for s in range(14):                     # 시드를 바꿔가며 가능한지 확인
        got = attempt(mid, 700 + s)
        if got:
            break
    if got:
        best = (mid, got)
        lo = mid
    else:
        hi = mid

if not best:
    sys.exit("배치 실패")

scale, placed = best
sizes = [placed[n][4] / VW * 100 for n in NAMES]
print(f"// {VW}x{VH} · 기준 {scale:.1f}vw · 여백 {GAP}px · 기울기 사다리 ±33° · 잉크 충돌 판정")
print(f"const {'LAYOUT_SM' if MOBILE else 'LAYOUT'} = [")
for n in NAMES:
    gx, gy, gw, gh, size_px, deg = placed[n]
    cx = (gx + gw / 2) * CELL / VW * 100
    cy = (gy + gh / 2) * CELL / VH * 100
    sz = size_px / VW * 100
    # 크기가 같으니 크기에서 깊이를 만들 수 없다. dim·blur 는 중립값으로 둔다 —
    # 밝기 위계는 field.js 의 에셋별 TONE 이 이미 잡아 놓았다.
    print(f"  {{ x: {cx:.0f}, y: {cy:.0f}, size: {sz:.0f}, rot: {deg:.0f}, "
          f"dim: 1.00, blur: 0.0 }},   // {n}")
print("];")
print(f"// 크기 {min(sizes):.0f}~{max(sizes):.0f}vw")

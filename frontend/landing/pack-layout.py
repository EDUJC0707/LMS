#!/usr/bin/env python3
"""히어로 모티프 배치 계산.

겹치지 않게 · 뷰포트 안에 · 크기는 비슷하게. 다만 **균등 난수로 뿌리면 안 된다** —
고르게 흩어진 배치는 무작위인데도 평평하고 투박하게 읽힌다. 그래서 세 가지를 넣는다.

1. 뭉침과 빔 — 다음 자리를 고를 때 이미 놓인 것 바로 옆(여백 직후)을 선호하기도 하고
   멀리 떨어진 곳을 선호하기도 한다. 확률을 섞으면 자연스러운 군집이 생긴다.
2. 회전 — 전부 정립해 있으면 스티커를 붙인 것처럼 보인다. 각자 다르게 기울인다.
   회전은 잉크 모양을 바꾸므로 충돌 판정도 회전 후 마스크로 한다.
3. 깊이 — 크기를 미세하게 흔들고(±12%), 작은 것은 조금 흐리고 어둡게 한다.
   같은 평면에 붙은 것이 아니라 공간에 떠 있는 것으로 읽힌다.

정렬 금지: 두 개가 같은 x 나 y 에 놓이면 즉시 격자로 보이므로 최소 간격을 강제한다.

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
GAP = 11 if MOBILE else 16            # 잉크 사이 최소 여백(px)
# 가장자리 여유. field.js 가 런타임에 개체를 최대 ±15px 흔들기 때문에(시차 8px +
# 자율부유 6px) 여기서 그만큼을 미리 빼둬야 한다. 10px 로 두면 왼쪽·위가 잘렸다.
EDGE = 30
TILT = 34                             # 최대 기울기(도)
TILT_MIN = 7                          # 정립 금지 — 0°에 가까우면 스티커로 읽힌다
NO_ALIGN = 3.0                        # 중심이 x·y 둘 다 이만큼 가까우면 거부

# 크기를 난수로만 흔들면 우연히 다 비슷해지는 판이 나온다. 그래서 배수를 미리
# 사다리로 깔고 섞는다 — 큰 것·중간·작은 것이 **반드시** 섞여 있게 보장된다
# (사용자 지시 2026-07-28: "각각을 막 좀 비정규적이게").
# 등차가 아니라 아래로 몰린 분포다. 큰 놈 둘셋이 주인공이고 나머지가 배경이 된다.
RAMP = [1.46, 1.30, 1.12, 0.98, 0.90, 0.84, 0.78, 0.73, 0.68, 0.62]
JITTER = 0.06                         # 사다리 위에 얹는 미세 흔들기 — 등차 티를 지운다

# 텍스트 뒤는 지나가도 된다(사용자 지시 2026-07-28) — 톤 위계가 잡혀 있어
# 배경(피크 휘도 68)이 헤드라인(116)보다 어둡기 때문이다. 대신 강사는 금지다.
TEACHER = HERE / "assets" / "teacher" / "nobg" / "02-검정티-턱손.webp"
TEACHER_H = 0.44 if MOBILE else 0.88      # index.html .teacher height
TEACHER_RIGHT = -0.14 if MOBILE else 0.09  # index.html .teacher right
TEACHER_PAD = 26          # 인물 실루엣 주변 여유(px)

GW, GH = VW // CELL, VH // CELL
rng = np.random.default_rng(20260728)

MASKS = {n: (np.array(Image.open(MOTIFS / f"{n}.webp").convert("RGBA").split()[3]) > 24)
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

    # 강사와 그 오른쪽 전부를 막는다(사용자 지시 2026-07-28).
    # 세로는 강사가 실제로 차지하는 구간만 — 모바일은 인물이 하단에만 있어
    # 전 높이를 막으면 상단 우측을 통째로 버리게 된다.
    ti = Image.open(TEACHER)
    th = min(TEACHER_H * VH, 900)
    tw = th * ti.width / ti.height
    left = VW - TEACHER_RIGHT * VW - tw - TEACHER_PAD
    top = VH - th - TEACHER_PAD
    f[max(0, int(top // CELL)):, max(0, int(left // CELL)):] = True
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

    # 배수를 이름에 무작위로 짝지어 놓고 **큰 것부터** 배치한다.
    # 큰 것이 가장 놓기 어려우므로 나중에 돌리면 자리가 남지 않는다.
    mult = list(RAMP[:len(order)])
    r.shuffle(mult)
    plan = sorted(zip(order, mult, zones), key=lambda p: -p[1])

    occ = FORBID.copy()
    placed, centers = {}, []

    for n, mu, (zx1, zx2, zy1, zy2) in plan:
        size_px = int(VW * scale / 100 * mu * (1 + r.uniform(-JITTER, JITTER)))
        deg = float(r.uniform(TILT_MIN, TILT)) * (1 if r.random() < .5 else -1)
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
print(f"// {VW}x{VH} · 기준 {scale:.1f}vw · 여백 {GAP}px · 기울기 ±{TILT}° · 잉크 충돌 판정")
print(f"const {'LAYOUT_SM' if MOBILE else 'LAYOUT'} = [")
for n in NAMES:
    gx, gy, gw, gh, size_px, deg = placed[n]
    cx = (gx + gw / 2) * CELL / VW * 100
    cy = (gy + gh / 2) * CELL / VH * 100
    sz = size_px / VW * 100
    # 깊이 — 작은 것은 멀리 있는 것처럼 조금 흐리고 어둡게
    t = (sz - min(sizes)) / max(1e-6, max(sizes) - min(sizes))
    dim = round(0.74 + 0.26 * t, 2)
    blur = round(1.1 * (1 - t), 1)
    print(f"  {{ x: {cx:.0f}, y: {cy:.0f}, size: {sz:.0f}, rot: {deg:.0f}, "
          f"dim: {dim}, blur: {blur} }},   // {n}")
print("];")
print(f"// 크기 {min(sizes):.0f}~{max(sizes):.0f}vw")

#!/usr/bin/env python3
"""히어로 모티프 배치 계산 — 겹치지 않게, 최대한 크게, 뷰포트 안에.

원(바운딩박스)으로 재면 손해가 크다. DNA 는 대각선 나선이라 잉크가 22.8% 뿐이고
나머지 77% 는 투명인데, 원으로 판정하면 그 빈 공간까지 자리를 차지한다.
그래서 **실제 알파만으로 충돌을 판정**한다.

금지구역은 헤드라인과 nav 뿐이다. 강사 뒤는 지나가도 된다(사용자 지시 2026-07-28).

  python3 pack-layout.py            # 데스크탑 1440x900
  python3 pack-layout.py --mobile   # 390x844
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
MOTIFS = HERE / "assets" / "motifs"
NAMES = ["atom", "dna", "mitochondria", "chloroplast", "synapse",
         "population", "element", "tectonics", "universe"]

MOBILE = "--mobile" in sys.argv
VW, VH = (390, 844) if MOBILE else (1440, 900)
CELL = 4                      # 점유 격자 한 칸(px)
NAV = 64                      # 상단 nav 높이(px)
GAP = 10 if MOBILE else 14    # 잉크 사이 최소 여백(px)

# 헤드라인 실측 박스(px). 브라우저에서 잰 값 기준.
HEAD = (int(VW * .04), int(VW * .52), int(VH * .36), int(VH * .70)) if not MOBILE \
    else (int(VW * .04), int(VW * .96), int(VH * .34), int(VH * .56))

GW, GH = VW // CELL, VH // CELL
rng = np.random.default_rng(11)


def load_masks():
    """각 모티프의 알파를 정사각 배열로. 값은 0/1."""
    out = {}
    for n in NAMES:
        a = np.array(Image.open(MOTIFS / f"{n}.webp").convert("RGBA").split()[3])
        out[n] = (a > 24)
    return out


MASKS = load_masks()
# 형태가 성긴 것은 크게 — 잉크 비율의 역수를 완만하게 반영
INK = {n: MASKS[n].mean() for n in NAMES}
WEIGHT = {n: (0.42 / INK[n]) ** 0.42 for n in NAMES}


def stamp(n, size_px):
    """모티프를 격자 해상도로 줄인 불린 마스크 + 여백 팽창."""
    g = max(3, size_px // CELL)
    m = np.array(Image.fromarray(MASKS[n].astype(np.uint8) * 255)
                 .resize((g, g), Image.BILINEAR)) > 90
    # 여백은 마스크를 부풀려 확보한다 — 이웃 잉크가 GAP 안으로 못 들어온다
    pad = max(1, GAP // CELL)
    if pad:
        k = np.zeros_like(m)
        for dy in range(-pad, pad + 1):
            for dx in range(-pad, pad + 1):
                if dx * dx + dy * dy > pad * pad:
                    continue
                k |= np.roll(np.roll(m, dy, 0), dx, 1)
        m = k
    return m


def forbidden_grid():
    f = np.zeros((GH, GW), bool)
    f[: (NAV + 6) // CELL, :] = True                     # nav
    x1, x2, y1, y2 = HEAD
    f[y1 // CELL: y2 // CELL, x1 // CELL: x2 // CELL] = True
    return f


FORBID = forbidden_grid()


def try_pack(scale, tries=900):
    """size = weight * scale (vw). 큰 것부터 놓는다."""
    occ = FORBID.copy()
    order = sorted(NAMES, key=lambda n: -WEIGHT[n])
    placed = {}
    for n in order:
        size_px = int(VW * WEIGHT[n] * scale / 100)
        if size_px < 8:
            return None
        m = stamp(n, size_px)
        gh, gw = m.shape
        if gh >= GH or gw >= GW:
            return None
        ok = False
        for _ in range(tries):
            gy = int(rng.integers(0, GH - gh))
            gx = int(rng.integers(0, GW - gw))
            if (occ[gy:gy + gh, gx:gx + gw] & m).any():
                continue
            occ[gy:gy + gh, gx:gx + gw] |= m
            placed[n] = (gx, gy, gw, gh, size_px)
            ok = True
            break
        if not ok:
            return None
    return placed


best = None
lo, hi = 4.0, 60.0
for _ in range(22):
    mid = (lo + hi) / 2
    got = try_pack(mid)
    if got:
        best = (mid, got)
        lo = mid
    else:
        hi = mid

if not best:
    sys.exit("배치 실패")

scale, placed = best
print(f"// {VW}x{VH} · 기준 배율 {scale:.1f} · 잉크 기준 충돌 판정 · 여백 {GAP}px")
rows = []
for n in NAMES:
    gx, gy, gw, gh, size_px = placed[n]
    cx = (gx + gw / 2) * CELL / VW * 100
    cy = (gy + gh / 2) * CELL / VH * 100
    rows.append((n, cx, cy, size_px / VW * 100))

print(f"const {'LAYOUT_SM' if MOBILE else 'LAYOUT'} = [")
for n, cx, cy, sz in rows:
    print(f"  {{ x: {cx:.0f}, y: {cy:.0f}, size: {sz:.0f} }},   // {n}")
print("];")
print(f"// 크기 범위 {min(r[3] for r in rows):.0f}~{max(r[3] for r in rows):.0f}vw")

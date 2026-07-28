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
# 계산 격자. 모바일은 화면이 좁아 같은 4px 이 상대적으로 큰 오차가 된다 —
# 21vw 짜리 모티프에 4px 양자화면 브라우저 렌더와 어긋나 실제로 366px² 겹쳤다.
# 2px 로 잘게 쓰면 오차가 절반이 되고, 셀 수가 4배지만 모바일은 화면이 작아 상쇄된다.
CELL = 2 if MOBILE else 4
NAV = 64
# 잉크 사이 최소 여백. **런타임 상대 이동을 여기서 덮는다** — field.js 가 개체마다
# 위상이 다른 자율 부유(±6px)를 주므로 이웃 둘이 서로에게 최대 12px 다가온다.
# 시차는 전원이 같은 방향이라 상대 거리를 바꾸지 않는다. 12px + 여유 = 24.
# 잉크 사이 최소 여백.
#
# 한동안 22~30px 을 썼는데, 그 근거("런타임에 이웃이 서로 ±12px 다가온다")는
# **모티프가 DOM 요소이던 시절의 것**이다. 지금은 오프스크린에 한 번 구워 통째로
# 그리므로(field.js drawImage(ink,0,0)) 상대 이동이 **0** 이다. 움직이는 것은 먼지뿐.
#
# 그래서 남은 오차는 계산과 렌더의 차이뿐이다 — 격자 양자화(CELL 4px), 회전
# 리샘플링, 브라우저의 축소 필터. 8px 이면 그 전부를 덮는다(브라우저 잉크 픽셀로 검증).
# 여백을 줄인 만큼 크기와 뭉침이 동시에 늘어난다.
GAP = 8 if MOBILE else 8
# 가장자리 여유. 이것도 옛 런타임 흔들림(±15px)을 덮으려던 값이었다 — 지금은
# 모티프가 고정이라 잘릴 일이 없고, 화면에 딱 붙지 않을 만큼만 남긴다.
EDGE = 10
# 기울기는 난수로 뽑지 않는다. 뽑아 보니 10개 중 5개가 16~17°에 몰려 **전부 같은
# 방향으로 기운 정렬**이 됐다 — 무작위는 뭉치기 때문이다. 그래서 각도를 사다리로
# 깔고 섞는다: 좌우 균형이 보장되고, 0° 근처(스티커처럼 보이는 각)가 비어 있다.
TILT_SET = [-33, -26, -19, -12, -7, 7, 12, 19, 26, 33]
TILT_JIT = 3                          # 사다리 위 미세 흔들기 — 등차 티를 지운다

# 손으로 못박은 기울기. 사다리에서 빼서 나머지에게 나눠 준다.
# 판이 꽉 차 있어 한 개만 돌려서는 빈자리가 안 나오므로, 못박고 **전체를 다시 푼다**.
PIN_TILT = {"dna": -7}                # 2026-07-28 사용자 지시: 이중나선을 오른쪽으로 +10°
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
# index.html 의 .teacher bottom(바닥 띄움)은 여기 없다 — 금지선이 전 높이 세로선이라
# 인물이 위아래로 움직여도 모티프 배치가 달라지지 않기 때문이다.

GW, GH = VW // CELL, VH // CELL
rng = np.random.default_rng(20260728)

# 임계값 6 — **실제 렌더보다 넓게** 잡는다. 브라우저는 768px 원본을 216px 로 줄이면서
# 가느다란 끝단을 조금 더 퍼뜨리는데, 여기서 넉넉히 잡아야 그 차이를 덮는다.
# (임계 12 + 여백 24px 로는 atom↔synapse 가 81px² 겹쳤다 — 브라우저 실측으로 확인)
MASKS = {n: (np.array(Image.open(MOTIFS / f"{n}.webp").convert("RGBA").split()[3]) > 6)
         for n in NAMES}


def stamp(n, size_px, deg):
    """회전·축소한 잉크 마스크 + 여백 팽창.

    **회전으로 캔버스가 커진 만큼 격자도 키워야 한다.** expand=True 는 그림을
    담으려고 캔버스를 최대 1.41배까지 늘리는데, 그걸 회전 전 크기(size_px)의
    격자로 줄이면 발자국이 그 배수만큼 작아진다 — 화면에서는 회전 후 크기로
    자리를 차지하므로 패커만 "안 겹친다"고 믿게 된다.
    (이 버그로 여백을 24 → 30px 까지 키워도 dna↔element 가 1215px² 겹쳤다.
     브라우저에서 잉크 픽셀로 재서 잡았다.)
    """
    base = Image.fromarray(MASKS[n].astype(np.uint8) * 255)
    img = base.rotate(deg, resample=Image.BILINEAR, expand=True, fillcolor=0) if deg else base
    grow = img.width / base.width          # 회전으로 커진 배수
    g = max(4, int(round(size_px * grow / CELL)))
    # 줄일 때의 문턱도 낮게. 90 으로 자르면 가느다란 가지가 통째로 사라져
    # "여기는 비었다" 고 잘못 판정한다
    m = np.array(img.resize((g, g), Image.BILINEAR)) > 40
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




# 구도. **존 격자를 버렸다.**
#
# 빈 공간을 격자로 쪼개 칸마다 하나씩 배정하면 구도는 통제되지만, 판을 걷어놓고 보면
# 위 4개 / 가운데 3개 / 아래 3개로 **줄이 보인다**. 격자에서 뽑은 이상 격자가 남는다.
#
# 그래서 자리는 자유 배치(거부 표집)로 뽑고, 대신 **유기적인지를 점수로 재서** 여러 판
# 중 가장 흐트러진 것을 고른다. "유기적"을 눈대중이 아니라 수로 정의한 것이다.
#
#   ① 뭉침과 빔    최근접이웃 거리의 변동계수(CV). 고르게 흩어지면 0 에 가깝고,
#                  어떤 둘은 붙고 어떤 곳은 비면 커진다. 이게 클수록 유기적이다.
#   ② 정렬 벌점    x 나 y 가 비슷한 쌍의 수. 격자·줄이 보이는 원인이 이것뿐이다.
#   ③ 퍼짐         한 구석에 몰려도 CV 는 높게 나온다. 그걸 막는 항.
ALIGN_TOL = 0.055                     # 이 비율(화면 기준) 안이면 "같은 줄"로 센다
# 정렬 벌점을 세게 건다. 줄이 보이는 것이 "격자 같다"의 유일한 원인이고,
# 뭉침(CV)은 여백이 허락하는 만큼만 올라가므로 가중치를 더 줘도 소용이 없다.
W_CV, W_ALIGN, W_SPREAD = 2.6, 0.22, 1.5


def organic_score(centers):
    """클수록 유기적. centers 는 (x%, y%) 목록."""
    n = len(centers)
    px = [(c[0] / 100 * VW, c[1] / 100 * VH) for c in centers]

    nn = []
    for i in range(n):
        d = min(math.dist(px[i], px[j]) for j in range(n) if j != i)
        nn.append(d)
    mean = sum(nn) / n
    cv = (sum((d - mean) ** 2 for d in nn) / n) ** .5 / mean if mean else 0

    tolx, toly = ALIGN_TOL * VW, ALIGN_TOL * VH
    align = sum(1 for i in range(n) for j in range(i + 1, n)
                if abs(px[i][0] - px[j][0]) < tolx or abs(px[i][1] - px[j][1]) < toly)

    mx = sum(p[0] for p in px) / n
    my = sum(p[1] for p in px) / n
    sx = (sum((p[0] - mx) ** 2 for p in px) / n) ** .5 / VW
    sy = (sum((p[1] - my) ** 2 for p in px) / n) ** .5 / VH
    spread = sx + sy

    return W_CV * cv - W_ALIGN * align + W_SPREAD * spread, cv, align, spread


def attempt(scale, seed):
    """자유 배치. 잉크가 넓은 것부터 놓고, 빈 곳이면 어디든 받는다."""
    r = np.random.default_rng(seed)
    order = list(NAMES)
    r.shuffle(order)

    free = [v for v in TILT_SET[:len(order)] if v not in PIN_TILT.values()]
    r.shuffle(free)
    it = iter(free)
    tilts = [PIN_TILT.get(n) for n in order]
    tilts = [v if v is not None else next(it) for v in tilts]
    # 잉크가 넓은 것(chromosome·element)이 뒤로 밀리면 자리가 없다
    plan = sorted(zip(order, tilts), key=lambda p: -MASKS[p[0]].mean())

    occ = FORBID.copy()
    placed, centers = {}, []

    for n, base_deg in plan:
        size_px = int(VW * scale / 100 * SIZE_EQ)
        # 못박은 것은 흔들지 않는다 — 지시한 각도 그대로여야 한다
        deg = float(base_deg if n in PIN_TILT else base_deg + r.uniform(-TILT_JIT, TILT_JIT))
        m = stamp(n, size_px, deg)
        gh, gw = m.shape
        if gh >= GH or gw >= GW:
            return None
        ok = False
        for _ in range(2600):
            gx = int(r.integers(0, GW - gw))
            gy = int(r.integers(0, GH - gh))
            if (occ[gy:gy + gh, gx:gx + gw] & m).any():
                continue
            cx = (gx + gw / 2) * CELL / VW * 100
            cy = (gy + gh / 2) * CELL / VH * 100
            # 사실상 겹쳐 보이는 중복만 거부한다. 줄서기는 점수가 걸러낸다
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


# ① 들어가는 최대 크기를 찾는다
lo, hi, fit_scale = 4.0, 50.0, None
for _ in range(18):
    mid = (lo + hi) / 2
    if any(attempt(mid, 700 + s) for s in range(16)):
        fit_scale = mid
        lo = mid
    else:
        hi = mid
if fit_scale is None:
    sys.exit("배치 실패")

# ② 최대치에서 조금 물러선다. 꽉 채우면 놓을 자리가 하나뿐이라 어떤 판을 뽑아도
#    같은 모양이 나온다 — 흐트러질 여유를 4% 만 남긴다.
# 최대치의 90%. 꽉 채우면 놓을 자리가 하나뿐이라 어떤 판을 뽑아도 같은 모양이 나온다
# (실측: 100% 에서 유효 후보 9판, 90% 에서 400판). 흐트러질 여유를 사는 값이다.
scale = fit_scale * 0.90

# ③ 그 크기로 여러 판을 뽑아 **가장 유기적인 것**을 고른다.
#    자유 배치는 판마다 모양이 크게 달라서, 고르는 일이 곧 디자인이다.
cands = []
for s in range(1400):
    got = attempt(scale, 5000 + s)
    if not got:
        continue
    centers = [((gx + gw / 2) * CELL / VW * 100, (gy + gh / 2) * CELL / VH * 100)
               for gx, gy, gw, gh, _, _ in (got[n] for n in NAMES)]
    cands.append((organic_score(centers), got))
if not cands:
    sys.exit("후보 없음")
cands.sort(key=lambda c: -c[0][0])
(sc, cv, align, spread), placed = cands[0]
worst = cands[-1][0]
print(f"// 후보 {len(cands)}판 중 최고 — 점수 {sc:.2f}(최저 {worst[0]:.2f})"
      f" · 뭉침·빔 CV {cv:.2f} · 정렬쌍 {align} · 퍼짐 {spread:.2f}")
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

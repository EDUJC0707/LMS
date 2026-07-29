/**
 * 히어로 배경 — 먼지밭에 바람이 불고, 아주 작은 손전등이 지나간다.
 *
 * 두 겹이다.
 *
 * ① **먼지** 4000개가 화면 전체에 상시 떠 있다. 커서는 먼지를 끌고 오지 않는다.
 *    밀어낸다 — 지나가는 자리의 먼지가 밖으로 밀려나고 동시에 옅어지면서 빈 자리가
 *    생기고, 커서가 떠나면 서서히 되메워진다. 강사 뒤도 지난다(금지구역 없음).
 *
 * ② **모티프**는 한자리에 고정돼 있고, 커서가 닿은 **픽셀만** 드러난다.
 *    한 개가 통째로 뜨는 것이 아니라 "조금씩" 보여야 하므로(사용자 지시 2026-07-28:
 *    "굉장히 작은 flashlight"), 반응 단위가 개체가 아니라 픽셀이어야 한다.
 *
 *    그래서 DOM 요소 10개를 캔버스 한 장으로 바꿨다. 모티프를 오프스크린에 **한 번**
 *    구워 두고, 매 프레임 커서 자리에 작은 방사 그라디언트를 칠한 뒤
 *    `source-in` 으로 그 잉크를 찍어낸다. 프레임당 비용은 손전등 사각형(약 130×130)
 *    두 번뿐이고, 화면 전체를 다시 그리지 않는다.
 *
 *    개체별 opacity 로는 이게 불가능하다 — opacity 는 요소 전체에 걸리므로
 *    "원자의 왼쪽 고리만 보인다" 를 표현할 방법이 없다.
 *
 * 손전등은 바람 창보다 **작다**. 바람이 부드럽게 걷어낸 자리 안에서, 그보다 좁은
 * 빛이 잉크를 훑는다 — 걷힌 자리에서만 보인다는 인과는 그대로다.
 */

const CFG = {
  /* 먼지 — 값은 사용자가 디버그 패널에서 맞춰 확정(2026-07-28) */
  dust: 4000,
  dMin: 1.0, dMax: 4.0,
  aMin: 0.10, aMax: 0.40,
  twinkle: 0.40,     // 밝기 흔들림 폭(비율) — "살짝살짝씩 보이게"
  buckets: 8,        // 알파를 8단으로 양자화해 globalAlpha 쓰기를 8회로 묶는다
  home: 10,          // 바람이 없을 때의 자율 부유 반경(px)

  /* 바람 — 걷히는 범위. 손전등보다 넓다 */
  R: 0.10,           // 창 반경 = min(W,H) × 이 값
  Rmin: 70, Rmax: 130,
  push: 0.85,        // 밀어내는 거리 = R × 이 값
  sweep: 0.16,       // 커서 속도를 얼마나 물고 가는가(진행 방향 쓸림)
  swirl: 0.22,       // 접선 성분 — 완벽한 원형 링이 생기는 것을 깬다
  fade: 0.85,        // 걷힌 자리에서 먼지가 얼마나 옅어지는가
  kOut: 9.0,         // 밀릴 때(빠르게)
  kIn: 1.6,          // 되메워질 때(느리게) — 여기서 "되메워진다"가 보인다

  /* 손전등 — 모티프가 드러나는 범위. 아주 작다 */
  flash: 0.062,      // 반경 = min(W,H) × 이 값 (900 → 56px)
  flashMin: 34, flashMax: 92,
  soft: 0.42,        // 이 비율까지는 온전히 밝고, 그 밖은 가장자리로 사그라든다
  ink: 0.62,         // 손전등 한복판 모티프 불투명도. 피크 렌더휘도 ≈68
  lag: 11,           // 손전등이 커서를 따라붙는 속도. 붙으면 UI, 뒤처지면 물질
};

/* 먼지·워시 색. 에셋 심부 청색(H236)에서 조금 더 차가운 H224 '로열' 로 확정.
   **값은 CSS 의 --glow 가 원본이다.** 여기 상수는 그게 없을 때의 대비책일 뿐 —
   색을 두 파일에 적어 두면 반드시 한쪽만 고치는 날이 온다. */
const GLOW_FALLBACK = '#9EAEE1';
const readGlow = () => {
  const v = getComputedStyle(document.documentElement).getPropertyValue('--glow').trim();
  return /^#[0-9a-f]{6}$/i.test(v) ? v : GLOW_FALLBACK;
};
const rgb = hex => [1, 3, 5].map(i => parseInt(hex.substr(i, 2), 16));

/* 정적 먼지 캔버스들의 다시 그리기 콜백. nav 처럼 히어로 밖에 있는 조각이
   여기 등록되고, 디버그 패널이 먼지 값을 바꾸면 같이 다시 그려진다 —
   따로 두면 히어로만 바뀌어 이어짐이 깨진다. */
const statics = [];

/* 에셋별 톤. 중간휘도를 실측해 피크 렌더휘도를 전부 ≈68 로 맞춘 계수.
   element·tectonics 는 원래 어두워서(134·146) 계수가 높다. data.js UNITS 순서. */
const TONE = [0.61, 0.53, 0.61, 0.63, 0.58, 0.59, 0.61, 0.84, 0.78, 0.61];

/* 배치는 pack-layout.py 가 계산한다 — 손으로 잡지 않는다.
   존을 먼저 정하고 그 안에서 흔든다. 순수 난수는 고르게 흩어져 평평하고,
   군집 선호만 주면 한쪽으로 쏠린다. 순서는 data.js 의 UNITS 와 1:1.

   **크기는 전부 같고 자리는 고정이다**(데스크탑 15vw / 모바일 16vw). 리듬은
   자리와 회전에서만 나온다 — 회전은 난수가 아니라 사다리(±33°, 0° 근처는 빔)를
   섞어 좌우 균형과 분산을 강제한다. 난수로 뽑으면 뭉친다(실측: 10개 중 5개가 16~17°).
   강사와 그 오른쪽은 금지구역이라 데스크탑 좌표가 전부 좌측 절반에 모인다. */
const LAYOUT = [
  { x: 46, y: 21, size: 15, rot: 24,  dim: 1 },   // atom
  { x: 32, y: 64, size: 15, rot: -5,  dim: 1 },   // dna
  { x: 9,  y: 22, size: 15, rot: -20, dim: 1 },   // chromosome
  { x: 22, y: 20, size: 15, rot: -31, dim: 1 },   // mitochondria
  { x: 35, y: 38, size: 15, rot: 13,  dim: 1 },   // chloroplast
  { x: 48, y: 47, size: 15, rot: -24, dim: 1 },   // synapse
  { x: 14, y: 45, size: 15, rot: 5,   dim: 1 },   // population
  { x: 25, y: 83, size: 15, rot: -11, dim: 1 },   // element
  { x: 43, y: 81, size: 15, rot: 19,  dim: 1 },   // tectonics
  { x: 10, y: 84, size: 15, rot: 33,  dim: 1 },   // universe
];

const LAYOUT_SM = [
  { x: 18, y: 20, size: 16, rot: 5,   dim: 1 },   // atom
  { x: 23, y: 41, size: 16, rot: 21,  dim: 1 },   // dna
  { x: 15, y: 73, size: 16, rot: -29, dim: 1 },   // chromosome
  { x: 34, y: 85, size: 16, rot: 9,   dim: 1 },   // mitochondria
  { x: 20, y: 59, size: 16, rot: -14, dim: 1 },   // chloroplast
  { x: 15, y: 80, size: 16, rot: -33, dim: 1 },   // synapse
  { x: 34, y: 72, size: 16, rot: -17, dim: 1 },   // population
  { x: 34, y: 34, size: 16, rot: -6,  dim: 1 },   // element
  { x: 15, y: 30, size: 16, rot: 30,  dim: 1 },   // tectonics
  { x: 19, y: 92, size: 16, rot: 27,  dim: 1 },   // universe
];

const isSmall = () => matchMedia('(max-width: 860px)').matches;
const rand = (a, b) => a + Math.random() * (b - a);
const clamp01 = v => (v < 0 ? 0 : v > 1 ? 1 : v);

export function mountField(root, units) {
  const GLOW = readGlow();
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* 포인터가 바람을 일으킬 자격이 있는가 — **실제 이벤트로만 판정한다.**
     마운트 시점 matchMedia('(hover:hover) and (pointer:fine)') 는 터치 노트북과
     헤드리스에서 참이라, 그걸 믿으면 영영 오지 않을 pointermove 를 기다리며
     히어로가 검정으로 남는다. 기본값은 false(=자율 배회가 대신 분다)이고,
     마우스/펜 pointermove 가 한 번 들어온 뒤에야 바람이 커서 소유로 넘어간다. */
  let FINE = false;

  /* ── 워시 — 바람이 지나간 자리의 옅은 빛 ── */
  const wash = document.createElement('canvas');
  wash.className = 'wash';
  wash.width = wash.height = 256;
  root.append(wash);
  {
    const wctx = wash.getContext('2d');
    // 색은 팔레트에서 파생한다 — rgb 를 여기 적어 두면 팔레트를 바꿔도 빛만 옛 색이다
    const [r0, g0, b0] = rgb(GLOW);
    const g = wctx.createRadialGradient(112, 104, 0, 128, 128, 128);
    g.addColorStop(0, `rgba(${r0},${g0},${b0},.070)`);
    g.addColorStop(.42, `rgba(${Math.round(r0 * .78)},${Math.round(g0 * .8)},${b0},.030)`);
    g.addColorStop(1, 'rgba(0,0,0,0)');
    wctx.fillStyle = g;
    wctx.fillRect(0, 0, 256, 256);
  }

  /* ── 모티프 — 캔버스 두 장.
     ink 는 오프스크린이고 한 번만 굽는다(자리가 고정이라 다시 구울 일이 없다).
     lit 은 화면에 붙어 매 프레임 손전등 모양으로 ink 를 찍어낸다. */
  const lit = document.createElement('canvas');
  lit.className = 'motifs';
  root.append(lit);
  const lctx = lit.getContext('2d');
  const ink = document.createElement('canvas');
  const ictx = ink.getContext('2d');
  const imgs = [];
  let baked = false;

  /* ── 먼지 ────────────────────────────────────────────────
     DPR 은 1 로 고정한다. 매 프레임 지우고 4000번 찍는 레이어라 백킹 픽셀 수가
     곧 프레임 비용이고, 1~4px 짜리 점에 2배 해상도는 아무 의미가 없다. */
  const dustCv = document.createElement('canvas');
  dustCv.className = 'dust';
  root.append(dustCv);
  const dctx = dustCv.getContext('2d');

  const makeDust = n => Array.from({ length: n }, () => {
    // 중심에서 밀어낼 방향이 정해지지 않는 입자(d≈0)를 위한 고정 탈출 방향.
    // 이게 없으면 커서 정중앙의 먼지가 제자리에 남아 구멍 한가운데 점이 박힌다.
    const a = rand(0, Math.PI * 2);
    return {
      u: Math.random(), v: Math.random(),        // 홈 위치(정규화) — resize 에 견딘다
      x: 0, y: 0, hx: 0, hy: 0,
      d: rand(CFG.dMin, CFG.dMax),
      a0: rand(CFG.aMin, CFG.aMax),
      ex: Math.cos(a), ey: Math.sin(a),
      s1: rand(.05, .13), s2: rand(.05, .13), ph: rand(0, 6.28),
      tw: rand(.25, .8), tph: rand(0, 6.28),     // 반짝임 속도·위상
    };
  });
  let dust = makeDust(CFG.dust);
  const bucket = Array.from({ length: CFG.buckets }, () => []);

  let W = 0, H = 0, R = 100, R2 = 1, FR = 56;

  /* 모티프를 오프스크린에 굽는다. 자리가 고정이므로 resize 때만 다시 굽는다.
     톤은 canvas filter 로 미리 태운다 — 매 프레임 filter 를 거는 것과 달리
     한 번만 래스터되므로 프레임 비용이 0 이다. */
  const bake = () => {
    if (!imgs.length || !W || !H) return;
    const L = isSmall() ? LAYOUT_SM : LAYOUT;
    ink.width = Math.round(W);
    ink.height = Math.round(H);
    ictx.setTransform(1, 0, 0, 1, 0, 0);
    ictx.clearRect(0, 0, W, H);
    const canFilter = 'filter' in ictx;
    L.forEach((p, i) => {
      const img = imgs[i];
      if (!img || !img.naturalWidth) return;
      const s = p.size / 100 * W;
      const tone = TONE[i] * p.dim;
      ictx.save();
      ictx.translate(p.x / 100 * W, p.y / 100 * H);
      ictx.rotate(p.rot * Math.PI / 180);
      if (canFilter) ictx.filter = `saturate(1.35) brightness(${tone})`;
      else ictx.globalAlpha = tone;      // filter 미지원 — 어두워지는 결과는 같다
      ictx.drawImage(img, -s / 2, -s / 2, s, s);
      ictx.restore();
    });
    ictx.filter = 'none';
    baked = true;
  };

  const fit = () => {
    const r = root.getBoundingClientRect();
    W = r.width; H = r.height;

    // 창 반경. 화면이 좁으면 같이 좁아진다 — vw 로 고정하면 모바일에서 화면
    // 절반이 통째로 걷힌다
    const m = Math.min(W, H);
    R = Math.max(CFG.Rmin, Math.min(CFG.Rmax, CFG.R * m));
    R2 = 2 * R * R;
    FR = Math.max(CFG.flashMin, Math.min(CFG.flashMax, CFG.flash * m));

    const ws = 2.6 * R;
    wash.style.width = wash.style.height = ws + 'px';
    wash.style.margin = `${-ws / 2}px 0 0 ${-ws / 2}px`;

    for (const cv of [dustCv, lit]) {
      cv.width = Math.round(W);
      cv.height = Math.round(H);
      cv.style.width = W + 'px';
      cv.style.height = H + 'px';
    }
    dctx.fillStyle = GLOW;                 // resize 가 컨텍스트 상태를 지운다

    for (const p of dust) { p.hx = p.u * W; p.hy = p.v * H; p.x = p.hx; p.y = p.hy; }
    bake();
  };

  /* 이미지는 다 받은 뒤에 굽는다. 반쯤 받은 상태로 구우면 빈 캔버스가 남고,
     자리가 고정이라 다시 구울 계기가 영영 오지 않는다. */
  units.slice(0, LAYOUT.length).forEach((u, i) => {
    const img = new Image();
    img.decoding = 'async';
    img.src = u.asset.replace(/^assets\/motifs\//, 'assets/motifs/768/');
    imgs[i] = img;
    (img.decode ? img.decode() : Promise.resolve()).catch(() => {}).then(bake);
  });

  fit();
  addEventListener('resize', fit);

  /* ── 입력 — 이벤트에서는 기록만. 물리는 rAF 에서만 돈다 ── */
  let pxN = .5, pyN = .5, idle = 99, wgt = 0, scrollP = 0;
  root.parentElement.addEventListener('pointermove', e => {
    // 손가락은 바람을 일으키지 않는다 — 스크롤 중 pointermove 가 쏟아진다
    if (e.pointerType === 'touch') return;
    const r = root.getBoundingClientRect();
    pxN = clamp01((e.clientX - r.left) / r.width);
    pyN = clamp01((e.clientY - r.top) / r.height);
    idle = 0;
    if (!FINE) { FINE = true; wgt = 1; }   // 첫 마우스 입력에서 인계 — 깜빡이지 않게
  }, { passive: true });
  addEventListener('scroll', () => { scrollP = clamp01(scrollY / innerHeight); }, { passive: true });

  /* ── 렌더 ───────────────────────────────────────────────── */
  let sx = .5, sy = .5, fx = .5, fy = .5;    // 바람의 눈(정규화)
  let lx = .5, ly = .5;                      // 손전등(정규화) — 바람보다 조금 빠르다
  let vx = 0, vy = 0;                        // 바람의 속도(px/s) — 진행 방향 쓸림용
  let raf = 0, t0 = 0, prev = 0;
  let prevRect = null;

  const paint = (t, dt) => {
    /* ① 바람의 눈. 포인터가 있으면 포인터가 전부 가져간다 */
    let tx, ty;
    if (FINE) {
      idle += dt;
      // 2.5초 정지하면 바람이 잦아든다. 켜질 때 빠르고 꺼질 때 느리다
      wgt = clamp01(wgt + (idle < 2.5 ? 3.0 : -0.9) * dt);
      fx += (pxN - fx) * (1 - Math.exp(-9.0 * dt));
      fy += (pyN - fy) * (1 - Math.exp(-9.0 * dt));
      tx = fx; ty = fy;
    } else {
      // 주기가 비배수라 눈이 루프를 못 찾는다
      tx = .50 + .30 * Math.sin(t * .110) + .07 * Math.sin(t * .041) + .18 * scrollP;
      ty = .46 + .20 * Math.sin(t * .170 + 1.1) + .06 * Math.sin(t * .067) + .30 * scrollP;
      wgt = 1;
    }
    const nsx = sx + (tx - sx) * (1 - Math.exp(-6.0 * dt));
    const nsy = sy + (ty - sy) * (1 - Math.exp(-6.0 * dt));
    // 속도는 정규화 좌표가 아니라 px/s 로 — 화면 비율에 따라 쓸림이 달라지면 안 된다
    const nvx = dt > 0 ? (nsx - sx) * W / dt : 0;
    const nvy = dt > 0 ? (nsy - sy) * H / dt : 0;
    vx += (nvx - vx) * (1 - Math.exp(-7.0 * dt));
    vy += (nvy - vy) * (1 - Math.exp(-7.0 * dt));
    sx = nsx; sy = nsy;
    lx += (tx - lx) * (1 - Math.exp(-CFG.lag * dt));
    ly += (ty - ly) * (1 - Math.exp(-CFG.lag * dt));

    const SX = sx * W, SY = sy * H;

    /* ② 워시 */
    wash.style.transform = `translate3d(${SX.toFixed(1)}px,${SY.toFixed(1)}px,0)`;
    wash.style.opacity = wgt.toFixed(3);

    /* ③ 먼지 — 밀려나고, 쓸려가고, 옅어진다 */
    for (const b of bucket) b.length = 0;
    const push = CFG.push * R, sweep = CFG.sweep, swirl = CFG.swirl * R;
    const NB = CFG.buckets, aTop = CFG.aMax * (1 + CFG.twinkle);

    for (const p of dust) {
      // 홈은 가만히 있지 않는다 — 바람이 없어도 아주 느리게 부유한다
      const hx = p.hx + Math.sin(t * p.s1 + p.ph) * CFG.home;
      const hy = p.hy + Math.cos(t * p.s2 + p.ph * 1.7) * CFG.home * .8;

      const gx = SX - hx, gy = SY - hy;
      const d2 = gx * gx + gy * gy;
      const w = Math.exp(-d2 / R2) * wgt;

      let tgx = hx, tgy = hy;
      if (w > .004) {
        const d = Math.sqrt(d2);
        const inv = 1 / (d + 1e-3);
        let ux = -gx * inv, uy = -gy * inv;    // 커서 반대 방향
        // 정중앙에서는 방향이 정의되지 않는다 — 입자 고유의 탈출 방향으로 대체
        const c = Math.exp(-d2 / (0.05 * R2));
        ux = ux * (1 - c) + p.ex * c;
        uy = uy * (1 - c) + p.ey * c;
        // 접선 성분은 완벽한 방사 대칭을 깬다. 없으면 구멍이 정확한 원이 된다
        tgx = hx + (ux * push - uy * swirl + vx * sweep) * w;
        tgy = hy + (uy * push + ux * swirl + vy * sweep) * w;
      }
      // 밀릴 때 빠르고 되메워질 때 느리다. 이 비대칭이 "걷힌다"를 만든다
      const dd = (tgx - hx) * (tgx - hx) + (tgy - hy) * (tgy - hy);
      const cur = (p.x - hx) * (p.x - hx) + (p.y - hy) * (p.y - hy);
      const e = 1 - Math.exp(-(dd > cur ? CFG.kOut : CFG.kIn) * dt);
      p.x += (tgx - p.x) * e;
      p.y += (tgy - p.y) * e;

      // 밀려나면서 옅어진다. 이게 없으면 밀린 먼지가 경계에 쌓여 링이 보인다
      const a = p.a0 * (1 + CFG.twinkle * Math.sin(t * p.tw + p.tph)) * (1 - CFG.fade * w);
      if (a <= 0.004) continue;
      bucket[Math.min(NB - 1, (a / aTop * NB) | 0)].push(p);
    }

    dctx.clearRect(0, 0, W, H);
    for (let i = 0; i < NB; i++) {
      const b = bucket[i];
      if (!b.length) continue;
      dctx.globalAlpha = aTop * (i + .5) / NB;
      for (const p of b) dctx.fillRect(p.x - p.d / 2, p.y - p.d / 2, p.d, p.d);
    }
    dctx.globalAlpha = 1;

    /* ④ 손전등 — 커서가 닿은 픽셀의 잉크만 찍어낸다.
       화면 전체가 아니라 손전등 사각형만 건드린다. 지난 프레임 자리도 함께
       지워야 잔상이 남지 않는다. */
    const LX = lx * W, LY = ly * H;
    const r = FR, pad = 2;
    const rect = [LX - r - pad, LY - r - pad, 2 * (r + pad), 2 * (r + pad)];
    if (prevRect) lctx.clearRect(...prevRect);
    lctx.clearRect(...rect);
    if (baked && wgt > .004) {
      const a = CFG.ink * wgt;
      const g = lctx.createRadialGradient(LX, LY, 0, LX, LY, r);
      g.addColorStop(0, `rgba(255,255,255,${a})`);
      g.addColorStop(CFG.soft, `rgba(255,255,255,${a * .82})`);
      g.addColorStop(1, 'rgba(255,255,255,0)');
      lctx.fillStyle = g;
      lctx.fillRect(...rect);
      // source-in: 방금 칠한 빛의 알파로 잉크를 오려낸다. 결과 알파 = 빛 × 잉크
      lctx.globalCompositeOperation = 'source-in';
      lctx.drawImage(ink, rect[0], rect[1], rect[2], rect[3], rect[0], rect[1], rect[2], rect[3]);
      lctx.globalCompositeOperation = 'source-over';
    }
    prevRect = rect;
  };

  const frame = now => {
    if (!t0) { t0 = now; prev = now; }
    const dt = Math.min(.05, (now - prev) / 1000);
    prev = now;
    paint((now - t0) / 1000, dt);
    raf = requestAnimationFrame(frame);
  };

  /* 디버그 패널(debug.js, ⌘⌥D) 전용 훅. 값을 CSS 로 뺄 수 없는 것들(입자 개수·
     물리 상수)을 실시간으로 만지기 위한 창구다. 읽는 쪽이 없으면 아무 일도 하지
     않고, debug.js 는 단축키를 누르기 전까지 내려받지도 않는다. */
  window.__field = {
    cfg: CFG,
    // n 을 cfg 에도 반영한다 — 안 하면 패널이 읽는 cfg.dust 와 실제 입자 수가
    // 갈라져, 초기화나 재열기 때 엉뚱한 개수로 돌아간다
    rebuild(n) { if (n != null) CFG.dust = n; dust = makeDust(CFG.dust); fit(); statics.forEach(f => f()); },
    refit() { fit(); statics.forEach(f => f()); },
  };

  if (reduce) {
    /* 움직임만 없다. 구도는 완성돼 보여야 한다.
       포인터 분기를 끄면 자율항이 wgt 1 로 돌아 한 프레임에 구도가 잡힌다.
       커서로 걷어내는 연출을 그대로 두면 이 사용자에게는 먼지밭만 남는다. */
    FINE = false;
    paint(0, 1);
  } else {
    raf = requestAnimationFrame(frame);
    // 히어로가 화면에서 나가면 멈춘다
    new IntersectionObserver(([e]) => {
      if (e.isIntersecting) { if (!raf) { prev = performance.now(); raf = requestAnimationFrame(frame); } }
      else if (raf) { cancelAnimationFrame(raf); raf = 0; }
    }, { threshold: 0 }).observe(root.parentElement);
  }
}

/**
 * nav 의 먼지 — 히어로 먼지밭을 위로 이어 붙인다.
 *
 * nav 는 항상 불투명 검정이라 그 아래 히어로 먼지를 가로로 잘라 먹는다. 여기서
 * 이어 주지 않으면 화면 맨 위 64px 만 텅 빈 띠로 남아 "덮개"라는 전제가 깨진다.
 *
 * **애니메이션하지 않는다**(사용자 지시 2026-07-28: "hover하면 움직일 필요는 없고
 * 그냥 연속성을 위해"). 화면 맨 위에서 계속 움직이는 것은 그 자체가 방해이고,
 * rAF 를 하나 더 도는 값어치도 없다. resize 와 디버그 패널 조작 때만 다시 그린다.
 *
 * 밀도는 히어로와 **면적당으로** 맞춘다 — 개수를 맞추면 좁은 띠에 몰려 눈에 띈다.
 */
export function mountNavDust(host) {
  const cv = document.createElement('canvas');
  cv.className = 'navdust';
  host.prepend(cv);
  const ctx = cv.getContext('2d');

  const draw = () => {
    const r = host.getBoundingClientRect();
    const W = Math.round(r.width), H = Math.round(r.height);
    if (!W || !H) return;
    cv.width = W; cv.height = H;
    cv.style.width = W + 'px';
    cv.style.height = H + 'px';
    ctx.fillStyle = readGlow();

    // 히어로가 기준으로 삼는 뷰포트 면적. 같은 밀도가 되도록 개수를 환산한다
    const n = Math.max(8, Math.round(CFG.dust * (W * H) / (innerWidth * innerHeight)));
    for (let i = 0; i < n; i++) {
      ctx.globalAlpha = rand(CFG.aMin, CFG.aMax);
      const d = rand(CFG.dMin, CFG.dMax);
      ctx.fillRect(Math.random() * W - d / 2, Math.random() * H - d / 2, d, d);
    }
    ctx.globalAlpha = 1;
  };

  statics.push(draw);
  addEventListener('resize', draw);
  draw();
  return draw;
}

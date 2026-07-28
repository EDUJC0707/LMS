/**
 * 히어로 배경 — 먼지밭에 바람이 분다.
 *
 * 화면에 아주 작은 먼지가 1200개 떠 있다. 이게 배경의 전부이자 **덮개**다.
 * 커서는 먼지를 끌고 오지 않는다. 밀어낸다 — 지나가는 자리의 먼지가 밖으로
 * 밀려나고 동시에 옅어지면서 빈 자리가 생기고, 커서가 떠나면 서서히 되메워진다.
 * 모티프는 **그 걷힌 자리에서만** 보인다. 원인과 결과가 하나다.
 *   (사용자 지시 2026-07-28: "먼지들이 ㅈㄴ 많은데 여기에 바람 부는거야
 *    따라오는게 아니라 걷히는걸로 가자")
 *
 * 그래서 먼지와 모티프는 **같은 창(窓) 함수**를 쓴다. w = exp(-d²/2R²).
 * 먼지는 w 만큼 밀려나고 옅어지고, 모티프는 w 만큼 드러난다. 둘이 다른 함수를
 * 쓰면 "먼지가 걷혀서 보이는 것"이 아니라 "둘이 각자 반응하는 것"으로 읽힌다.
 *
 * 가우시안을 쓰는 이유는 **경계가 없어서**다. 원형 마스크는 페더를 아무리
 * 부드럽게 해도 원 자체가 하나의 물체로 읽힌다(사용자 판정: "ㅈㄴ 촌스러워").
 *
 * 먼지는 강사 뒤도 지난다 — 금지구역이 없다(사용자 확인). 강사가 불투명하므로
 * 실루엣에서 자연히 가려질 뿐이다. 모티프만 강사 왼쪽으로 제한된다.
 */

const CFG = {
  /* 먼지. 개수·밝기만 디버그 패널이 만지고(⌘⌥D), 나머지는 여기서 확정한다.
     노브를 늘려 봐야 고를 수 있는 건 "얼마나 자글자글한가" 하나뿐이었다. */
  dust: 1200,        // 1440x900 기준 100px² 당 0.9개
  dMin: 1.4, dMax: 2.4,
  aMin: 0.12, aMax: 0.30,
  twinkle: 0.45,     // 밝기 흔들림 폭(비율) — "살짝살짝씩 보이게"
  buckets: 8,        // 알파를 8단으로 양자화해 globalAlpha 쓰기를 8회로 묶는다
  home: 9,           // 바람이 없을 때의 자율 부유 반경(px)

  /* 바람. 창 반경 R 만 패널이 만진다. */
  R: 0.15,           // 창 반경 = min(W,H) × 이 값
  Rmin: 110, Rmax: 190,
  push: 0.85,        // 밀어내는 거리 = R × 이 값
  sweep: 0.16,       // 커서 속도를 얼마나 물고 가는가(진행 방향 쓸림)
  swirl: 0.22,       // 접선 성분 — 완벽한 원형 링이 생기는 것을 깬다
  fade: 0.85,        // 걷힌 자리에서 먼지가 얼마나 옅어지는가
  kOut: 9.0,         // 밀릴 때(빠르게)
  kIn: 1.6,          // 되메워질 때(느리게) — 여기서 "되메워진다"가 보인다

  /* 모티프 */
  peak: 0.60,        // 피크 렌더휘도 ≈68. 헤드라인(110)보다 어두워야 위계가 선다
  gamma: 0.8,
  blurMax: 5,
  scaleMax: 0.035,
  drift: 6,
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

   **크기는 전부 같다**(데스크탑 15vw / 모바일 16vw). 사용자 지시다. 그래서 리듬은
   자리와 회전에서만 나온다 — 회전은 난수가 아니라 사다리(±33°, 0° 근처는 빔)를
   섞어 좌우 균형과 분산을 강제한다. 난수로 뽑으면 뭉친다(실측: 10개 중 5개가 16~17°).
   강사와 그 오른쪽은 금지구역이라 데스크탑 좌표가 전부 좌측 절반에 모인다. */
const LAYOUT = [
  { x: 46, y: 21, size: 15, rot: 24,  dim: 1, blur: 0 },   // atom
  { x: 32, y: 64, size: 15, rot: -5,  dim: 1, blur: 0 },   // dna
  { x: 9,  y: 22, size: 15, rot: -20, dim: 1, blur: 0 },   // chromosome
  { x: 22, y: 20, size: 15, rot: -31, dim: 1, blur: 0 },   // mitochondria
  { x: 35, y: 38, size: 15, rot: 13,  dim: 1, blur: 0 },   // chloroplast
  { x: 48, y: 47, size: 15, rot: -24, dim: 1, blur: 0 },   // synapse
  { x: 14, y: 45, size: 15, rot: 5,   dim: 1, blur: 0 },   // population
  { x: 25, y: 83, size: 15, rot: -11, dim: 1, blur: 0 },   // element
  { x: 43, y: 81, size: 15, rot: 19,  dim: 1, blur: 0 },   // tectonics
  { x: 10, y: 84, size: 15, rot: 33,  dim: 1, blur: 0 },   // universe
];

const LAYOUT_SM = [
  { x: 18, y: 20, size: 16, rot: 5,   dim: 1, blur: 0 },   // atom
  { x: 23, y: 41, size: 16, rot: 21,  dim: 1, blur: 0 },   // dna
  { x: 15, y: 73, size: 16, rot: -29, dim: 1, blur: 0 },   // chromosome
  { x: 34, y: 85, size: 16, rot: 9,   dim: 1, blur: 0 },   // mitochondria
  { x: 20, y: 59, size: 16, rot: -14, dim: 1, blur: 0 },   // chloroplast
  { x: 15, y: 80, size: 16, rot: -33, dim: 1, blur: 0 },   // synapse
  { x: 34, y: 72, size: 16, rot: -17, dim: 1, blur: 0 },   // population
  { x: 34, y: 34, size: 16, rot: -6,  dim: 1, blur: 0 },   // element
  { x: 15, y: 30, size: 16, rot: 30,  dim: 1, blur: 0 },   // tectonics
  { x: 19, y: 92, size: 16, rot: 27,  dim: 1, blur: 0 },   // universe
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

  /* ── 워시 — 바람이 지나간 자리의 옅은 빛. 256px 백킹을 CSS 로 늘린다.
     1100px div 를 DPR2 에서 승격하면 레이어 메모리가 19MB 다. 256px 면 0.26MB 이고
     매끄러운 그라디언트라 업스케일 아티팩트가 보이지 않는다. */
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

  /* ── 먼지 ────────────────────────────────────────────────
     DPR 은 1 로 고정한다. 매 프레임 지우고 1200번 찍는 레이어라 백킹 픽셀 수가
     곧 프레임 비용이고, 1.5px 짜리 점에 2배 해상도는 아무 의미가 없다. */
  const dustCv = document.createElement('canvas');
  dustCv.className = 'dust';
  const dctx = dustCv.getContext('2d', { alpha: true });

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
  // 알파 버킷 — globalAlpha 쓰기를 프레임당 1200회에서 8회로 줄인다
  const bucket = Array.from({ length: CFG.buckets }, () => []);

  /* ── 모티프 ─────────────────────────────────────────────── */
  const wrap = document.createElement('div');
  wrap.className = 'motifs';
  root.append(wrap);
  root.append(dustCv);        // 먼지는 모티프보다 앞이다 — 덮개니까

  const motifs = units.slice(0, LAYOUT.length).map((u, i) => {
    const el = document.createElement('div');
    el.className = 'big';
    const img = document.createElement('img');
    const base = u.asset.replace(/^assets\/motifs\//, '');
    img.src = `assets/motifs/768/${base}`;
    img.srcset = `assets/motifs/512/${base} 512w, assets/motifs/768/${base} 768w`;
    img.sizes = '16vw';
    img.alt = '';
    img.decoding = 'async';
    el.append(img);
    wrap.append(el);
    return {
      el, img, cx: 0, cy: 0, rot: 0,
      tone: TONE[i], b0: 0,
      f: 0, b: -1,
      // 개체마다 반응 속도가 다르다 — 같으면 10개가 한 파면으로 들어온다
      kIn: rand(3.2, 5.1),
      s1: rand(.055, .11), s2: rand(.055, .11), ph: rand(0, 6.28),
    };
  });

  let W = 0, H = 0, R = 150, R2 = 1;

  const fit = () => {
    const r = root.getBoundingClientRect();
    W = r.width; H = r.height;
    const L = isSmall() ? LAYOUT_SM : LAYOUT;

    motifs.forEach((m, i) => {
      const p = L[i];
      m.el.style.left = p.x + '%';
      m.el.style.top = p.y + '%';
      m.el.style.setProperty('--size', p.size + 'vw');
      m.rot = p.rot;
      m.cx = p.x / 100 * W;
      m.cy = p.y / 100 * H;
      // 깊이 훅. 지금은 크기가 균일해 dim=1/blur=0 이지만, 배치가 바뀌어 크기가
      // 갈리면 패커가 다시 채워 넣는다 — 배선을 남겨 둔다
      m.tone = TONE[i] * p.dim;
      m.b0 = p.blur;
      m.b = -1;                            // filter 재계산 강제
      m.el.style.setProperty('--tone', m.tone.toFixed(3));
    });

    // 창 반경. 화면이 좁으면 같이 좁아진다 — vw 로 고정하면 모바일에서 화면
    // 절반이 통째로 걷힌다
    R = Math.max(CFG.Rmin, Math.min(CFG.Rmax, CFG.R * Math.min(W, H)));
    R2 = 2 * R * R;

    const ws = 2.6 * R;
    wash.style.width = wash.style.height = ws + 'px';
    wash.style.margin = `${-ws / 2}px 0 0 ${-ws / 2}px`;

    dustCv.width = Math.round(W);
    dustCv.height = Math.round(H);
    dustCv.style.width = W + 'px';
    dustCv.style.height = H + 'px';
    dctx.fillStyle = GLOW;                 // resize 가 컨텍스트 상태를 지운다

    for (const p of dust) { p.hx = p.u * W; p.hy = p.v * H; p.x = p.hx; p.y = p.hy; }
  };
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
  let vx = 0, vy = 0;                        // 그 속도(px/s) — 진행 방향 쓸림용
  let raf = 0, t0 = 0, prev = 0;

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

    const SX = sx * W, SY = sy * H;

    /* ② 워시 */
    wash.style.transform = `translate3d(${SX.toFixed(1)}px,${SY.toFixed(1)}px,0)`;
    wash.style.opacity = wgt.toFixed(3);

    /* ③ 먼지 — 밀려나고, 쓸려가고, 옅어진다 */
    for (const b of bucket) b.length = 0;
    const push = CFG.push * R, sweep = CFG.sweep, swirl = CFG.swirl * R;
    const NB = CFG.buckets;

    for (const p of dust) {
      // 홈은 가만히 있지 않는다 — 바람이 없어도 아주 느리게 부유한다
      const hx = p.hx + Math.sin(t * p.s1 + p.ph) * CFG.home;
      const hy = p.hy + Math.cos(t * p.s2 + p.ph * 1.7) * CFG.home * .8;

      const gx = SX - hx, gy = SY - hy;
      const d2 = gx * gx + gy * gy;
      const w = Math.exp(-d2 / R2) * wgt;      // 먼지와 모티프가 공유하는 창 함수

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
      const k = dd > cur ? CFG.kOut : CFG.kIn;
      const e = 1 - Math.exp(-k * dt);
      p.x += (tgx - p.x) * e;
      p.y += (tgy - p.y) * e;

      // 밀려나면서 옅어진다. 이게 없으면 밀린 먼지가 경계에 쌓여 링이 보인다
      const a = p.a0 * (1 + CFG.twinkle * Math.sin(t * p.tw + p.tph)) * (1 - CFG.fade * w);
      if (a <= 0.004) continue;
      const bi = Math.min(NB - 1, (a / CFG.aMax / (1 + CFG.twinkle) * NB) | 0);
      bucket[bi].push(p);
    }

    dctx.clearRect(0, 0, W, H);
    for (let i = 0; i < NB; i++) {
      const b = bucket[i];
      if (!b.length) continue;
      dctx.globalAlpha = CFG.aMax * (1 + CFG.twinkle) * (i + .5) / NB;
      for (const p of b) dctx.fillRect(p.x - p.d / 2, p.y - p.d / 2, p.d, p.d);
    }
    dctx.globalAlpha = 1;

    /* ④ 모티프 — 먼지가 걷힌 만큼만 보인다. 먼지와 같은 w 를 쓴다 */
    const lx = -(sx - .5), ly = -(sy - .5) * .6;
    for (const m of motifs) {
      const ddx = SX - m.cx, ddy = SY - m.cy;
      const target = Math.exp(-(ddx * ddx + ddy * ddy) / R2) * wgt;
      const k = target > m.f ? m.kIn : m.kIn * 0.45;   // 빠질 때 느리게 = 여운
      m.f += (target - m.f) * (1 - Math.exp(-k * dt));

      const f = m.f, amp = 6 + 10 * f;
      const dx = lx * amp + Math.sin(t * m.s1 + m.ph) * CFG.drift;
      const dy = ly * amp + Math.cos(t * m.s2 + m.ph * 1.7) * CFG.drift * .8;

      m.el.style.opacity = (CFG.peak * Math.pow(f, CFG.gamma)).toFixed(3);
      m.el.style.transform =
        `translate(-50%,-50%) rotate(${m.rot}deg) ` +
        `translate3d(${dx.toFixed(1)}px,${dy.toFixed(1)}px,0) scale(${(1 + CFG.scaleMax * f).toFixed(4)})`;

      // blur 는 정수로 양자화 — 값이 바뀔 때만 재래스터한다(제스처당 개체별 6회)
      const b = Math.round(m.b0 + CFG.blurMax * Math.pow(1 - f, 1.4));
      if (b !== m.b) {
        m.b = b;
        m.img.style.filter = (b ? `blur(${b}px) ` : '') + 'saturate(1.35) brightness(var(--tone))';
      }
    }
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
       커서로 걷어내는 연출을 그대로 두면 이 사용자에게는 영원히 먼지밭만 남는다. */
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
    const heroArea = innerWidth * innerHeight;
    const n = Math.max(8, Math.round(CFG.dust * (W * H) / heroArea));
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

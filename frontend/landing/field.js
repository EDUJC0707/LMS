/**
 * 히어로 배경 — 커서가 지나간 곳만 드러난다.
 *
 * 포인터가 있는 기기에서는 **빛이 곧 포인터다**(사용자 지시 2026-07-28:
 * "hover가 안가면 안보여야돼"). 커서가 멈춘 채 오래 지나면 빛도 함께 사그라들어
 * 화면이 검정으로 돌아간다. 자율 배회(sun)는 포인터가 없는 기기 전용 대체다 —
 * 터치에서 검은 화면만 남기지 않기 위한 것이며, 데스크탑에서는 개입하지 않는다.
 *
 * 감쇠는 레이어 마스크가 아니라 **개체별 스칼라**다. 원형 마스크를 쓰면 페더를
 * 아무리 부드럽게 해도 원이 하나의 물체로 읽힌다(사용자 판정: "ㅈㄴ 촌스러워").
 * 개체별로 옮기면 화면에 남는 경계선은 모티프 자신의 실루엣뿐이 된다.
 *
 * DOM 에 원은 없다. 애니메이션되는 속성은 opacity·transform·(정수 양자화된) filter,
 * 그리고 궤적 캔버스 1장뿐.
 */

const CFG = {
  peak: 0.60,      // 피크 렌더휘도 ≈68. 헤드라인(110)보다 어두워야 위계가 선다
  gamma: 0.8,      // opacity 는 일찍 올라온다
  blurMax: 5,      // blur 는 (1-f)^1.4 로 늦게 도착한다 — 지수를 달리해 복합 모션이 된다
  scaleMax: 0.035,
  drift: 6,        // 개별 자율 부유(px)
  stars: 130,      // 정적 별밭
  trail: 34,       // 커서를 따라오는 점
  Rk: 1.5,         // 감쇠 기준거리 = 최근접이웃 중위거리 × 1.5
  fall: 5.5,       // 1/(1+fall·d²) — 클수록 빛이 좁다("flashlight이 너무 크고")
};

/* 궤적·별밭 색. atom·synapse·universe 의 진한 청색 픽셀 평균 H236 계열 —
   배경과 전경이 같은 팔레트에서 나온다(index.html :root --glow 와 동일 값). */
const GLOW = '#A5A9DD';

/* 에셋별 톤. 중간휘도를 실측해 피크 렌더휘도를 전부 ≈68 로 맞춘 계수.
   element·tectonics 는 원래 어두워서(134·146) 계수가 높다. data.js UNITS 순서. */
const TONE = [0.61, 0.53, 0.61, 0.63, 0.58, 0.59, 0.61, 0.84, 0.78, 0.61];

/* 배치는 pack-layout.py 가 계산한다 — 손으로 잡지 않는다.
   존을 먼저 정하고 그 안에서 흔든다. 순수 난수는 고르게 흩어져 평평하고,
   군집 선호만 주면 한쪽으로 쏠린다. 순서는 data.js 의 UNITS 와 1:1.

   크기는 일부러 고르지 않다(10~24vw). 균등한 크기는 그 자체로 격자처럼 읽힌다.
   dim·blur 는 크기에서 따라나온 깊이값 — 작은 것은 멀리 있는 것처럼 처리한다.
   강사와 그 오른쪽은 금지구역이라 데스크탑 좌표가 전부 좌측 절반에 모인다. */
const LAYOUT = [
  { x: 42, y: 46, size: 15, rot: 33,  dim: 0.82, blur: 0.7 },   // atom
  { x: 10, y: 83, size: 20, rot: 19,  dim: 0.92, blur: 0.3 },   // dna
  { x: 29, y: 55, size: 13, rot: -26, dim: 0.79, blur: 0.9 },   // chromosome
  { x: 13, y: 58, size: 25, rot: 14,  dim: 1.00, blur: 0.0 },   // mitochondria
  { x: 11, y: 18, size: 12, rot: -10, dim: 0.77, blur: 1.0 },   // chloroplast
  { x: 31, y: 36, size: 22, rot: -22, dim: 0.96, blur: 0.2 },   // synapse
  { x: 43, y: 18, size: 14, rot: 26,  dim: 0.81, blur: 0.8 },   // population
  { x: 31, y: 81, size: 17, rot: -28, dim: 0.87, blur: 0.6 },   // element
  { x: 27, y: 20, size: 10, rot: 20,  dim: 0.74, blur: 1.1 },   // tectonics
  { x: 43, y: 71, size: 12, rot: 11,  dim: 0.76, blur: 1.0 },   // universe
];

const LAYOUT_SM = [
  { x: 69, y: 20, size: 34, rot: -29, dim: 0.91, blur: 0.4 },   // atom
  { x: 28, y: 19, size: 27, rot: 22,  dim: 0.84, blur: 0.7 },   // dna
  { x: 17, y: 86, size: 20, rot: -10, dim: 0.77, blur: 1.0 },   // chromosome
  { x: 17, y: 53, size: 23, rot: 30,  dim: 0.80, blur: 0.9 },   // mitochondria
  { x: 22, y: 31, size: 38, rot: 16,  dim: 0.95, blur: 0.2 },   // chloroplast
  { x: 26, y: 68, size: 26, rot: 31,  dim: 0.82, blur: 0.7 },   // synapse
  { x: 51, y: 12, size: 18, rot: -10, dim: 0.74, blur: 1.1 },   // population
  { x: 43, y: 41, size: 20, rot: -23, dim: 0.76, blur: 1.0 },   // element
  { x: 66, y: 35, size: 43, rot: -32, dim: 1.00, blur: 0.0 },   // tectonics
  { x: 82, y: 47, size: 24, rot: -24, dim: 0.81, blur: 0.8 },   // universe
];

const isSmall = () => matchMedia('(max-width: 860px)').matches;
const rand = (a, b) => a + Math.random() * (b - a);
const clamp01 = v => (v < 0 ? 0 : v > 1 ? 1 : v);
const median = a => { const s = [...a].sort((x, y) => x - y); return s[s.length >> 1]; };

export function mountField(root, units) {
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* 포인터가 광원을 가져갈 자격이 있는가 — **실제 이벤트로만 판정한다.**
     마운트 시점 matchMedia('(hover:hover) and (pointer:fine)') 는 터치 노트북과
     헤드리스에서 참이라, 그걸 믿으면 영영 오지 않을 pointermove 를 기다리며
     히어로가 검정으로 남는다. 그래서 기본값은 false(=자율 배회로 보인다)이고,
     마우스/펜 pointermove 가 한 번 들어온 뒤에야 빛이 커서 소유로 넘어간다. */
  let FINE = false;

  /* ── 워시 — 빛 자체. 256px 백킹을 CSS 로 늘린다.
     1100px div 를 DPR2 에서 승격하면 레이어 메모리가 19MB 다. 256px 면 0.26MB 이고
     매끄러운 그라디언트라 업스케일 아티팩트가 보이지 않는다. */
  const wash = document.createElement('canvas');
  wash.className = 'wash';
  wash.width = wash.height = 256;
  root.append(wash);
  const wctx = wash.getContext('2d');
  {
    // 중심을 살짝 비틀어 색이 한쪽으로 치우친다 — 빛이 움직이면 파란 쪽과 보라 쪽이
    // 서로 다른 영역을 훑는다. 크로스페이드 2장을 쓰지 않고 이걸로 근사한다.
    const g = wctx.createRadialGradient(112, 104, 0, 128, 128, 128);
    g.addColorStop(0, 'rgba(126,140,255,.090)');
    g.addColorStop(.42, 'rgba(96,104,214,.040)');
    g.addColorStop(.74, 'rgba(70,110,220,.013)');
    g.addColorStop(1, 'rgba(0,0,0,0)');
    wctx.fillStyle = g;
    wctx.fillRect(0, 0, 256, 256);
  }

  /* ── 별밭 — 정적. resize 때만 1회 그린다 */
  const dots = document.createElement('canvas');
  dots.className = 'dots';
  root.append(dots);
  const dctx = dots.getContext('2d');

  /* ── 궤적 — 커서를 따라오는 점들.
     뱀처럼 한 줄로 늘어놓지 않는다. 각자 다른 감쇠로 뒤처지고, 뒤처진 자기 좌표를
     중심으로 제 궤도를 돈다. 그래서 선이 아니라 무리로 읽힌다.
     DPR 을 1 로 고정한다 — 매 프레임 clear 하는 레이어라 백킹이 곧 프레임 비용이다. */
  const trail = document.createElement('canvas');
  trail.className = 'trail';
  const tctx = trail.getContext('2d');

  /* 점 하나를 스프라이트로 미리 굽는다. 사각형 fillRect 로 찍으면 1~2px 에서
     날카로운 픽셀 노이즈로 읽히고, 매 프레임 arc 를 쌓으면 패스 비용이 붙는다.
     32px 스프라이트 1장을 drawImage 로 늘리는 게 둘 다 피하는 유일한 방법이다. */
  const SPR = 32;
  const spr = document.createElement('canvas');
  spr.width = spr.height = SPR;
  {
    const c = spr.getContext('2d');
    const g = c.createRadialGradient(SPR / 2, SPR / 2, 0, SPR / 2, SPR / 2, SPR / 2);
    g.addColorStop(0, GLOW);
    g.addColorStop(.35, GLOW + 'AA');
    g.addColorStop(1, GLOW + '00');
    c.fillStyle = g;
    c.fillRect(0, 0, SPR, SPR);
  }

  const swarm = Array.from({ length: CFG.trail }, (_, i) => {
    const u = i / CFG.trail;
    return {
      x: -999, y: -999,
      k: 1.1 + 11 * Math.pow(1 - u, 1.9),   // 앞은 붙어오고 뒤는 한참 뒤처진다
      d: rand(3, 11) * (1 + u * 1.6),       // 지름(px) — 뒤로 갈수록 커지고 흐려진다
      orb: 6 + 46 * Math.pow(u, .8),        // 뒤처진 놈이 더 크게 돈다
      w: rand(.7, 2.3) * (Math.random() < .5 ? -1 : 1),
      w2: rand(.9, 1.7),
      ph: rand(0, 6.28),
      a: rand(.30, .80) * (1 - u * .62),
    };
  });

  /* ── 모티프 ─────────────────────────────────────────────── */
  const wrap = document.createElement('div');
  wrap.className = 'motifs';
  root.append(wrap);
  root.append(trail);          // 궤적은 모티프보다 앞이다 — 뒤에 두면 잉크에 묻힌다

  const motifs = units.slice(0, LAYOUT.length).map((u, i) => {
    const el = document.createElement('div');
    el.className = 'big';
    const img = document.createElement('img');
    const base = u.asset.replace(/^assets\/motifs\//, '');
    img.src = `assets/motifs/768/${base}`;
    img.srcset = `assets/motifs/512/${base} 512w, assets/motifs/768/${base} 768w`;
    img.sizes = '(max-width:860px) 47vw, 24vw';
    img.alt = '';
    img.decoding = 'async';
    el.append(img);
    wrap.append(el);
    return {
      el, img, cx: 0, cy: 0, rot: 0,
      tone: TONE[i], b0: 0,
      f: 0, b: -1,
      // 개체마다 반응 속도가 다르다 — 같으면 9개가 한 파면으로 들어온다
      kIn: rand(3.2, 5.1),
      s1: rand(.055, .11), s2: rand(.055, .11), ph: rand(0, 6.28),
    };
  });

  let W = 0, H = 0, Rpx = 1;

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
      // 깊이 — 작은 것은 더 어둡고 기본 흐림을 깔고 시작한다
      m.tone = TONE[i] * p.dim;
      m.b0 = p.blur;
      m.b = -1;                            // filter 재계산 강제
      m.el.style.setProperty('--tone', m.tone.toFixed(3));
    });

    // 감쇠 기준거리는 배치에서 나온다 — 화면이 좁으면 자동으로 좁아진다
    const nn = motifs.map(m => Math.min(...motifs
      .filter(o => o !== m)
      .map(o => Math.hypot(m.cx - o.cx, m.cy - o.cy))));
    Rpx = Math.max(120, median(nn) * CFG.Rk);

    const ws = 2.1 * Rpx;
    wash.style.width = wash.style.height = ws + 'px';
    wash.style.margin = `${-ws / 2}px 0 0 ${-ws / 2}px`;

    // 별밭은 resize 때만 1회 그린다
    const dpr = Math.min(devicePixelRatio || 1, 1.5);
    dots.width = Math.round(W * dpr);
    dots.height = Math.round(H * dpr);
    dots.style.width = W + 'px';
    dots.style.height = H + 'px';
    dctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    dctx.clearRect(0, 0, W, H);
    dctx.fillStyle = GLOW;
    for (let i = 0; i < CFG.stars; i++) {
      dctx.globalAlpha = rand(.04, .16);
      const rr = rand(.5, 1.4);
      dctx.fillRect(rand(0, W), rand(0, H), rr * 2, rr * 2);   // 패스 빌드 회피
    }
    dctx.globalAlpha = 1;

    // 궤적은 DPR 1. setTransform/resize 가 fillStyle 을 지우므로 여기서 다시 잡는다
    trail.width = Math.round(W);
    trail.height = Math.round(H);
    trail.style.width = W + 'px';
    trail.style.height = H + 'px';
    tctx.fillStyle = GLOW;
  };
  fit();
  addEventListener('resize', fit);

  /* ── 입력 — 이벤트에서는 기록만. sun 갱신은 rAF 에서만 한다 ── */
  let pxN = .5, pyN = .5, idle = 99, wgt = 0, scrollP = 0;
  root.parentElement.addEventListener('pointermove', e => {
    // 손가락은 광원을 가져가지 않는다 — 스크롤 중 pointermove 가 쏟아진다
    if (e.pointerType === 'touch') return;
    const r = root.getBoundingClientRect();
    pxN = clamp01((e.clientX - r.left) / r.width);
    pyN = clamp01((e.clientY - r.top) / r.height);
    idle = 0;
    if (!FINE) { FINE = true; wgt = 1; }   // 첫 마우스 입력에서 인계 — 깜빡이지 않게
  }, { passive: true });
  addEventListener('scroll', () => {
    scrollP = clamp01(scrollY / innerHeight);
  }, { passive: true });

  /* ── 렌더 ───────────────────────────────────────────────── */
  let sx = .62, sy = .42, fx = .5, fy = .5;
  let t0 = 0, prev = 0, raf = 0;

  const paint = (t, dt) => {
    /* ① 빛의 위치. 포인터가 있으면 포인터가 전부 가져간다 — 커서가 곧 광원이다.
       자율 배회는 포인터가 없는 기기에서만 쓴다. */
    let tx, ty;
    if (FINE) {
      idle += dt;
      // 2.5초 정지하면 사그라들기 시작한다. 켜질 때 빠르고 꺼질 때 느리다
      wgt = clamp01(wgt + (idle < 2.5 ? 3.0 : -0.9) * dt);
      fx += (pxN - fx) * (1 - Math.exp(-6.0 * dt));
      fy += (pyN - fy) * (1 - Math.exp(-6.0 * dt));
      tx = fx; ty = fy;
    } else {
      // 주기가 비배수라 눈이 루프를 못 찾는다
      tx = .50 + .30 * Math.sin(t * .110) + .07 * Math.sin(t * .041) + .18 * scrollP;
      ty = .46 + .20 * Math.sin(t * .170 + 1.1) + .06 * Math.sin(t * .067) + .30 * scrollP;
      wgt = 1;
    }
    // 2단 감쇠 — 손에서 떼어낸다. 붙으면 UI, 뒤처지면 물질
    sx += (tx - sx) * (1 - Math.exp(-3.3 * dt));
    sy += (ty - sy) * (1 - Math.exp(-3.3 * dt));

    /* ② 워시 — 쓰기 1회. 커서가 쉬면 함께 사그라든다 */
    wash.style.transform = `translate3d(${(sx * W).toFixed(1)}px,${(sy * H).toFixed(1)}px,0)`;
    wash.style.opacity = wgt.toFixed(3);

    /* ③ 궤적 — 무리가 커서를 뒤따른다 */
    tctx.clearRect(0, 0, W, H);
    // 커서가 없으면 궤적도 없다 — FINE 이 아닐 때 그리면 화면 한복판에 점 무리가 고인다
    if (FINE && wgt > .004) {
      const px = pxN * W, py = pyN * H;
      for (const p of swarm) {
        if (p.x < -500) { p.x = px; p.y = py; }
        p.x += (px - p.x) * (1 - Math.exp(-p.k * dt));
        p.y += (py - p.y) * (1 - Math.exp(-p.k * dt));
        // 궤도는 두 축의 주기가 달라 원이 아니라 리사주 곡선을 그린다
        const ax = p.x + Math.cos(t * p.w + p.ph) * p.orb;
        const ay = p.y + Math.sin(t * p.w * p.w2 + p.ph) * p.orb * .78;
        tctx.globalAlpha = p.a * wgt;
        tctx.drawImage(spr, ax - p.d / 2, ay - p.d / 2, p.d, p.d);
      }
      tctx.globalAlpha = 1;
    }

    /* ④ 모티프 — 빛의 반대로 밀린다(시차) */
    const SX = sx * W, SY = sy * H;
    const lx = -(sx - .5), ly = -(sy - .5) * .6;
    for (const m of motifs) {
      const d = Math.hypot(SX - m.cx, SY - m.cy) / Rpx;
      const target = 1 / (1 + CFG.fall * d * d);   // 어디서도 0 이 아니다 = 경계가 없다
      const k = target > m.f ? m.kIn : m.kIn * 0.45;   // 빠질 때 느리게 = 여운
      m.f += (target - m.f) * (1 - Math.exp(-k * dt));

      const f = m.f, amp = 6 + 10 * f;
      const dx = lx * amp + Math.sin(t * m.s1 + m.ph) * CFG.drift;
      const dy = ly * amp + Math.cos(t * m.s2 + m.ph * 1.7) * CFG.drift * .8;

      // 바닥값이 없다. 빛이 안 닿으면 0 이고, 커서가 쉬면 wgt 로 통째로 사그라든다
      m.el.style.opacity = (CFG.peak * wgt * Math.pow(f, CFG.gamma)).toFixed(3);
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

  if (reduce) {
    /* 움직임만 없다. 구도는 완성돼 보여야 한다.
       포인터 분기를 끄고(자율항 = wgt 1) 한 프레임만 그린다. 커서로 드러내는
       연출을 그대로 두면 이 사용자에게는 영원히 검은 화면만 남는다. */
    FINE = false;
    trail.remove();
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

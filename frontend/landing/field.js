/**
 * 히어로 배경 — 장막.
 *
 * 화면 전체에 통합과학 개념들이 **거대하게** 깔려 있지만 평상시엔 보이지 않는다.
 * 커서(또는 손가락) 주변 반경만 장막이 걷히듯 드러난다.
 *
 * 개별 아이콘을 하나씩 켜는 방식이 아니다 — 레이어 하나에 전부 그려두고
 * 방사형 마스크를 포인터에 붙여 그 안쪽만 보이게 한다. 그래서 두 개가 걸치면
 * 둘 다 부분적으로 드러나고, 큰 것 하나면 그 조각만 드러난다.
 *
 * 점(dots)은 마스크 밖에도 항상 있다. 아무것도 없는 검은 화면이면 만질 이유가
 * 없는데, 점이 미세하게 살아 움직이면 "여기 뭔가 있다"가 안내 문구 없이 전달된다.
 */

const R = {
  reveal: 300,      // 장막이 걷히는 반경(px)
  feather: 0.55,    // 가장자리가 풀어지는 비율 — 1에 가까울수록 부드럽다
  dots: 190,
  dotGlow: 260,     // 포인터 주변에서 점이 밝아지는 반경
};

/* 배치는 pack-layout.py 가 계산한다 — 손으로 잡지 않는다.
   잉크(알파)만으로 충돌을 판정하므로 DNA 처럼 성긴 형태는 더 크게 들어간다.
   금지구역은 헤드라인과 nav 뿐이고, 강사 뒤는 지나가도 된다.
   순서는 data.js 의 UNITS 와 1:1로 맞아야 한다. */
const LAYOUT = [
  { x: 61, y: 82, size: 21 },   // atom
  { x: 73, y: 33, size: 26 },   // dna
  { x: 35, y: 85, size: 19 },   // mitochondria
  { x: 52, y: 22, size: 18 },   // chloroplast
  { x: 82, y: 66, size: 22 },   // synapse
  { x: 9,  y: 22, size: 17 },   // population
  { x: 13, y: 83, size: 17 },   // element
  { x: 27, y: 23, size: 16 },   // tectonics
  { x: 89, y: 34, size: 18 },   // universe
];

const LAYOUT_SM = [
  { x: 34, y: 63, size: 33 },   // atom
  { x: 74, y: 77, size: 41 },   // dna
  { x: 30, y: 17, size: 29 },   // mitochondria
  { x: 69, y: 93, size: 28 },   // chloroplast
  { x: 22, y: 89, size: 34 },   // synapse
  { x: 16, y: 74, size: 27 },   // population
  { x: 83, y: 27, size: 27 },   // element
  { x: 69, y: 62, size: 25 },   // tectonics
  { x: 62, y: 15, size: 28 },   // universe
];

const isSmall = () => matchMedia('(max-width: 860px)').matches;
const rand = (a, b) => a + Math.random() * (b - a);

export function mountField(root, units) {
  /* ── 레이어 1: 점 — 마스크 밖에도 항상 보인다 ───────────────── */
  const canvas = document.createElement('canvas');
  canvas.className = 'dots';
  root.append(canvas);
  const ctx = canvas.getContext('2d');

  let dots = [];
  const seedDots = (w, h) => {
    dots = Array.from({ length: R.dots }, () => ({
      x: Math.random() * w,
      y: Math.random() * h,
      r: rand(0.5, 1.5),
      base: rand(0.06, 0.26),      // 평상시 밝기
      drift: rand(0.15, 0.5),      // 아주 느리게 떠다닌다
      dir: Math.random() * Math.PI * 2,
    }));
  };

  /* ── 레이어 2: 모티프 — 마스크가 걷히는 만큼만 보인다 ────────── */
  const veil = document.createElement('div');
  veil.className = 'veil';
  root.append(veil);

  units.slice(0, LAYOUT.length).forEach((u, i) => {
    const el = document.createElement('div');
    el.className = 'big';
    el.dataset.i = String(i);
    const img = document.createElement('img');
    img.src = u.asset;
    img.alt = '';
    img.decoding = 'async';
    img.loading = 'eager';   // 만졌을 때 바로 있어야 한다
    el.append(img);
    veil.append(el);
  });
  const bigs = [...veil.children];

  const place = () => {
    const L = isSmall() ? LAYOUT_SM : LAYOUT;
    bigs.forEach((el, i) => {
      const p = L[i];
      el.style.left = p.x + '%';
      el.style.top = p.y + '%';
      el.style.setProperty('--size', p.size + 'vw');
    });
  };

  const fit = () => {
    const dpr = Math.min(devicePixelRatio || 1, 2);
    const r = root.getBoundingClientRect();
    canvas.width = Math.round(r.width * dpr);
    canvas.height = Math.round(r.height * dpr);
    canvas.style.width = r.width + 'px';
    canvas.style.height = r.height + 'px';
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    seedDots(r.width, r.height);
    place();
  };
  fit();
  addEventListener('resize', fit);

  /* ── 포인터 ─────────────────────────────────────────────────
     마스크 중심은 CSS 변수로만 넘긴다. 매 프레임 DOM 을 만들거나 지우지 않는다. */
  let px = -9999, py = -9999;   // 화면 밖에서 시작 = 아무것도 안 보임
  let tx = px, ty = py;         // 뒤따라오는 값 — 커서에 살짝 늦게 붙어 부드럽다
  let active = false;

  const setVeil = (x, y, on) => {
    veil.style.setProperty('--mx', x + 'px');
    veil.style.setProperty('--my', y + 'px');
    veil.style.setProperty('--r', (on ? R.reveal : 0) + 'px');
  };

  let t = 0;
  const frame = () => {
    t += 0.006;
    tx += (px - tx) * 0.16;
    ty += (py - ty) * 0.16;
    setVeil(tx, ty, active);

    const { width: w, height: h } = canvas.getBoundingClientRect();
    ctx.clearRect(0, 0, w, h);
    for (const d of dots) {
      // 아주 느린 부유 — 정지해 있으면 죽은 화면으로 보인다
      d.x += Math.cos(d.dir + t) * d.drift * 0.14;
      d.y += Math.sin(d.dir + t * 0.8) * d.drift * 0.14;
      if (d.x < -4) d.x = w + 4; else if (d.x > w + 4) d.x = -4;
      if (d.y < -4) d.y = h + 4; else if (d.y > h + 4) d.y = -4;

      let a = d.base;
      if (active) {
        const dist = Math.hypot(tx - d.x, ty - d.y);
        if (dist < R.dotGlow) a += (1 - dist / R.dotGlow) * 0.75;
      }
      ctx.globalAlpha = Math.min(a, 1);
      ctx.fillStyle = '#fff';
      ctx.beginPath();
      ctx.arc(d.x, d.y, d.r, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.globalAlpha = 1;
    requestAnimationFrame(frame);
  };
  requestAnimationFrame(frame);

  const hero = root.parentElement;
  const toLocal = e => {
    const r = root.getBoundingClientRect();
    return [e.clientX - r.left, e.clientY - r.top];
  };

  hero.addEventListener('pointermove', e => {
    if (e.pointerType === 'touch') return;
    [px, py] = toLocal(e);
    if (!active) { tx = px; ty = py; active = true; }   // 첫 진입은 순간이동
  });
  hero.addEventListener('pointerleave', e => {
    if (e.pointerType === 'touch') return;
    active = false;
  });

  /* 터치 — 손가락을 따라 걷히고, 떼면 잠시 머물다 닫힌다 */
  let hold = 0;
  const touch = e => {
    [px, py] = toLocal(e);
    if (!active) { tx = px; ty = py; active = true; }
    clearTimeout(hold);
  };
  hero.addEventListener('pointerdown', e => { if (e.pointerType === 'touch') touch(e); }, { passive: true });
  hero.addEventListener('pointermove', e => { if (e.pointerType === 'touch') touch(e); }, { passive: true });
  hero.addEventListener('pointerup', e => {
    if (e.pointerType !== 'touch') return;
    hold = setTimeout(() => { active = false; }, 900);
  }, { passive: true });
}

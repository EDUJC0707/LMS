/**
 * 히어로 배경 — 화면이 빛을 받고, 천천히 어두워진다.
 *
 * 원판을 커서에 못 박아 두지 않는다. 그건 아무리 부드럽게 해도 원이었다
 * (사용자 판정 2026-07-28: "이게 찐 손전등이 아니라... 진짜 원이 아니라").
 *
 * 대신 **빛 밭(light field)** 을 하나 둔다. 화면을 12px 격자로 덮은 스칼라 장이고,
 * 매 프레임 두 가지가 일어난다.
 *
 *   ① 전체가 조금씩 어두워진다        F *= exp(-decay·dt)
 *   ② 커서 자리에 빛을 바른다          F += 덩어리 3개
 *
 * 그래서 밝은 모양은 원이 아니라 **커서가 지나간 길**이다. 빠르게 그으면 길게
 * 번지고, 천천히 움직이면 뭉치고, 멈추면 그 자리가 포화돼 계속 밝다. 손을 떼면
 * 그 길이 천천히 검정으로 돌아간다(잔광 3초+).
 *
 * 멈춰 있어도 원이 되지 않게, 빛은 완벽한 원 하나가 아니라 **느리게 도는 어긋난
 * 덩어리 셋**으로 바른다. 그래서 정지 상태에서도 모양이 계속 일렁인다.
 *
 * **이 밭 하나가 세 가지를 다 몰아준다**(사용자 확인) — 장치가 셋이면 셋으로 읽힌다.
 *   · 광량   — 밭을 그대로 옅게 깔면 "화면이 빛을 받은" 것이 된다
 *   · 모티프 — 밭을 문턱(감마)에 통과시켜 마스크로 쓴다. 그래서 조금씩만 드러난다
 *   · 먼지   — 밭의 **기울기**를 밀어내는 방향으로 쓴다. 방사 대칭이 아니라
 *             빛이 번진 모양을 따라 걷히므로 여기서도 원이 나오지 않는다
 *
 * 밭은 JS 배열로 돌린다. 캔버스에 두고 getImageData 로 읽으면 GPU→CPU 회수가
 * 매 프레임 끼어들어 프레임이 튄다. 화면에 올릴 때만 작은 ImageData 로 옮긴다.
 */

const CFG = {
  /* 먼지 — 사용자가 패널에서 맞춰 확정(2026-07-28) */
  dust: 4000,
  dMin: 1.0, dMax: 4.0,
  aMin: 0.10, aMax: 0.40,
  twinkle: 0.40,     // 밝기 흔들림 폭(비율)
  buckets: 8,        // 알파를 8단으로 양자화해 globalAlpha 쓰기를 8회로 묶는다
  home: 10,          // 빛이 없을 때의 자율 부유 반경(px)

  /* 빛 */
  /* 붓은 작다. 다만 **머물러서 다다르는 최대치는 그대로**다(사용자 지시
     2026-07-28: "붓은 더 작게 최대한 커진건 max 는 같게") — R 을 90→54 로 줄인
     만큼 dwellGain 을 2.0→4.0 으로 올려 Rb_max = 270px 을 유지한다. */
  R: 0.06,           // 붓 반경 = min(W,H) × 이 값 (900 → 54px)
  Rmin: 40, Rmax: 90,
  decay: 0.40,       // 초당 감쇠. 3초 뒤 30%, 6초 뒤 9% — "천천히 어두워진다"
  deposit: 2.8,      // 초당 바르는 양. decay 보다 커야 멈춘 자리가 포화돼 계속 밝다
  diffuse: 4.0,      // 번짐(셀²/초). 빛이 옆으로 스며든다
  dwellMax: 5.0,     // 머무름을 이 초까지 센다
  dwellGain: 4.0,    // 끝까지 머물면 붓이 5배 — 54 → 270px. 최대치는 예전과 같다
  moveHold: 70,      // 이 속도(px/s) 아래면 "머문다"로 본다
  cell: 12,          // 밭 격자(px). 작을수록 곱지만 셀 수가 제곱으로 는다

  /* 빛을 받아 일어나는 것들 */
  ink: 0.62,         // 모티프 최대 불투명도. 피크 렌더휘도 ≈68 < 헤드라인 110
  gMotif: 1.7,       // 모티프 문턱(감마). 클수록 아주 밝은 데서만 드러난다 = 조금씩
  push: 0.85,        // 먼지를 밀어내는 거리 = R × 이 값
  sweep: 0.16,       // 커서 속도를 얼마나 물고 가는가
  swirl: 0.22,       // 접선 성분
  fade: 0.85,        // 밝은 자리에서 먼지가 얼마나 옅어지는가
  kOut: 9.0,         // 밀릴 때(빠르게)
  kIn: 1.6,          // 되메워질 때(느리게) — 이 비대칭이 "걷힌다"를 만든다
};

/* 먼지·빛 색. 에셋 심부 청색(H236)에서 조금 더 차가운 H224 '로열' 로 확정.
   **값은 CSS 의 --glow 가 원본이다.** 여기 상수는 그게 없을 때의 대비책일 뿐. */
const GLOW_FALLBACK = '#9EAEE1';
const readGlow = () => {
  const v = getComputedStyle(document.documentElement).getPropertyValue('--glow').trim();
  return /^#[0-9a-f]{6}$/i.test(v) ? v : GLOW_FALLBACK;
};
const rgb = hex => [1, 3, 5].map(i => parseInt(hex.substr(i, 2), 16));

/* 정적 먼지 캔버스들의 다시 그리기 콜백. nav 처럼 히어로 밖에 있는 조각이
   여기 등록되고, 디버그 패널이 먼지 값을 바꾸면 같이 다시 그려진다. */
const statics = [];

/* 에셋별 톤. 중간휘도를 실측해 피크 렌더휘도를 전부 ≈68 로 맞춘 계수.
   element·tectonics 는 원래 어두워서(134·146) 계수가 높다. data.js UNITS 순서. */
const TONE = [0.61, 0.53, 0.61, 0.63, 0.58, 0.59, 0.61, 0.84, 0.78, 0.61];

/* 배치는 pack-layout.py 가 계산한다 — 손으로 잡지 않는다. 순서는 UNITS 와 1:1.
   크기는 전부 같고 자리는 고정이다(데스크탑 12vw / 모바일 13vw). **에셋 자체도
   잉크 긴 변이 캔버스의 95% 가 되게 통일해 구워 두었다** — 같은 vw 를 줘도 여백이
   제각각이면 보이는 크기가 다르다(정규화 전 DNA 는 74% 라 혼자 22% 작았다).
   리듬은 자리와
   회전에서만 나온다 — 회전은 난수가 아니라 사다리(±33°, 0° 근처는 빔)를 섞는다.
   강사와 그 오른쪽은 금지구역이라 데스크탑 좌표가 전부 좌측 절반에 모인다. */
const LAYOUT = [
  { x: 37, y: 21, size: 12, rot: -10, dim: 1 },   // atom
  { x: 37, y: 66, size: 12, rot: -17, dim: 1 },   // dna
  { x: 52, y: 61, size: 12, rot: 28,  dim: 1 },   // chromosome
  { x: 11, y: 72, size: 12, rot: -32, dim: 1 },   // mitochondria
  { x: 49, y: 37, size: 12, rot: 8,   dim: 1 },   // chloroplast
  { x: 12, y: 43, size: 12, rot: -27, dim: 1 },   // synapse
  { x: 32, y: 44, size: 12, rot: 12,  dim: 1 },   // population
  { x: 24, y: 80, size: 12, rot: 18,  dim: 1 },   // element
  { x: 18, y: 22, size: 12, rot: -7,  dim: 1 },   // tectonics
  { x: 42, y: 81, size: 12, rot: 31,  dim: 1 },   // universe
];

const LAYOUT_SM = [
  { x: 34, y: 45, size: 13, rot: -17, dim: 1 },   // atom
  { x: 35, y: 69, size: 13, rot: 8,   dim: 1 },   // dna
  { x: 30, y: 20, size: 13, rot: -10, dim: 1 },   // chromosome
  { x: 14, y: 43, size: 13, rot: -7,  dim: 1 },   // mitochondria
  { x: 29, y: 54, size: 13, rot: 31,  dim: 1 },   // chloroplast
  { x: 15, y: 92, size: 13, rot: 11,  dim: 1 },   // synapse
  { x: 21, y: 35, size: 13, rot: 26,  dim: 1 },   // population
  { x: 19, y: 81, size: 13, rot: -27, dim: 1 },   // element
  { x: 33, y: 89, size: 13, rot: -32, dim: 1 },   // tectonics
  { x: 15, y: 68, size: 13, rot: 16,  dim: 1 },   // universe
];

const isSmall = () => matchMedia('(max-width: 860px)').matches;
const rand = (a, b) => a + Math.random() * (b - a);
const clamp01 = v => (v < 0 ? 0 : v > 1 ? 1 : v);

export function mountField(root, units) {
  const GLOW = readGlow();
  const [GR, GG, GB] = rgb(GLOW);
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* 포인터가 빛을 바를 자격이 있는가 — **실제 이벤트로만 판정한다.**
     마운트 시점 matchMedia('(hover:hover) and (pointer:fine)') 는 터치 노트북과
     헤드리스에서 참이라, 그걸 믿으면 영영 오지 않을 pointermove 를 기다리며
     히어로가 검정으로 남는다. 기본값은 false(=자율 배회가 대신 바른다)이고,
     마우스/펜 pointermove 가 한 번 들어온 뒤에야 붓이 커서 소유로 넘어간다. */
  let FINE = false;

  /* ── 레이어. 아래에서 위로: 모티프 → 먼지. 먼지가 맨 위인 이유는 덮개라서다.
     **광량 레이어는 없다**(사용자 지시 2026-07-28: "왜 흰색 원이 커지지 뒤에?
     이거 그냥 흰색만 없애자"). 밭을 그대로 옅게 깔면 아무리 낮춰도 커다란 흰
     원반으로 읽힌다 — 원을 없애려고 시작한 일인데 원을 다시 그리고 있었다.
     빛은 이제 드러내고 걷어내기만 한다. */
  const mk = cls => { const c = document.createElement('canvas'); c.className = cls; root.append(c); return c; };
  const litCv = mk('motifs'), dustCv = mk('dust');
  const lctx = litCv.getContext('2d');
  const dctx = dustCv.getContext('2d');

  // 모티프 원판. 자리가 고정이라 한 번만 굽는다
  const ink = document.createElement('canvas');
  const ictx = ink.getContext('2d');
  const imgs = [];
  let baked = false;

  // 빛 밭을 모티프 마스크로 올리는 작은 캔버스
  const fB = document.createElement('canvas');
  const fbCtx = fB.getContext('2d');
  let F = null, Fs = null, FW = 0, FH = 0, imgB = null;

  const makeDust = n => Array.from({ length: n }, () => {
    // 밭의 기울기가 0 인 자리(빛의 한복판)에서 밀어낼 방향이 없다 — 입자마다
    // 고정 탈출 방향을 줘서 구멍 한가운데 점이 박히는 것을 막는다
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

  let W = 0, H = 0, R = 100;

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
    R = Math.max(CFG.Rmin, Math.min(CFG.Rmax, CFG.R * Math.min(W, H)));

    for (const cv of [litCv, dustCv]) {
      cv.width = Math.round(W);
      cv.height = Math.round(H);
      cv.style.width = W + 'px';
      cv.style.height = H + 'px';
    }
    dctx.fillStyle = GLOW;                 // resize 가 컨텍스트 상태를 지운다

    // 밭 격자. 셀은 정사각에 가깝게 — 가로세로 비가 다르면 빛이 타원으로 번진다
    const nw = Math.max(24, Math.round(W / CFG.cell));
    const nh = Math.max(16, Math.round(H / CFG.cell));
    if (nw !== FW || nh !== FH) {
      FW = nw; FH = nh;
      F = new Float32Array(FW * FH);
      Fs = new Float32Array(FW * FH);      // 번짐 계산용 여벌
      fB.width = FW; fB.height = FH;
      imgB = fbCtx.createImageData(FW, FH);
      // RGB 는 한 번만 채운다 — 매 프레임 다시 쓰면 픽셀당 3배를 헛되이 쓴다
      const d = imgB.data;
      for (let i = 0; i < FW * FH; i++) { d[i * 4] = GR; d[i * 4 + 1] = GG; d[i * 4 + 2] = GB; }
    }

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
  let pxN = .5, pyN = .5, scrollP = 0;
  root.parentElement.addEventListener('pointermove', e => {
    // 손가락은 빛을 바르지 않는다 — 스크롤 중 pointermove 가 쏟아진다
    if (e.pointerType === 'touch') return;
    const r = root.getBoundingClientRect();
    pxN = clamp01((e.clientX - r.left) / r.width);
    pyN = clamp01((e.clientY - r.top) / r.height);
    FINE = true;
  }, { passive: true });
  addEventListener('scroll', () => { scrollP = clamp01(scrollY / innerHeight); }, { passive: true });

  /* ── 밭 읽기 — 이중선형. 최근접으로 하면 12px 계단이 먼지 움직임에 드러난다 ── */
  const sample = (x, y) => {
    const u = x / CFG.cell - .5, v = y / CFG.cell - .5;
    let i = Math.floor(u), j = Math.floor(v);
    const fx = u - i, fy = v - j;
    if (i < 0) i = 0; else if (i > FW - 2) i = FW - 2;
    if (j < 0) j = 0; else if (j > FH - 2) j = FH - 2;
    const k = j * FW + i;
    const a = F[k], b = F[k + 1], c = F[k + FW], d = F[k + FW + 1];
    return (a + (b - a) * fx) * (1 - fy) + (c + (d - c) * fx) * fy;
  };

  /* ── 렌더 ───────────────────────────────────────────────── */
  let cx = .5, cy = .5;                      // 붓 위치(정규화)
  let vx = 0, vy = 0;                        // 그 속도(px/s) — 진행 방향 쓸림용
  let dwell = 0;                             // 한자리에 머문 시간(초)
  let raf = 0, t0 = 0, prev = 0;

  const paint = (t, dt) => {
    /* ① 붓 위치. 포인터가 있으면 포인터가 전부 가져간다 */
    let tx, ty;
    if (FINE) { tx = pxN; ty = pyN; }
    else {
      // 주기가 비배수라 눈이 루프를 못 찾는다
      tx = .50 + .30 * Math.sin(t * .110) + .07 * Math.sin(t * .041) + .18 * scrollP;
      ty = .46 + .20 * Math.sin(t * .170 + 1.1) + .06 * Math.sin(t * .067) + .30 * scrollP;
    }
    const ncx = cx + (tx - cx) * (1 - Math.exp(-11 * dt));
    const ncy = cy + (ty - cy) * (1 - Math.exp(-11 * dt));
    // 속도는 정규화 좌표가 아니라 px/s 로 — 화면 비율에 따라 쓸림이 달라지면 안 된다
    const nvx = dt > 0 ? (ncx - cx) * W / dt : 0;
    const nvy = dt > 0 ? (ncy - cy) * H / dt : 0;
    vx += (nvx - vx) * (1 - Math.exp(-7 * dt));
    vy += (nvy - vy) * (1 - Math.exp(-7 * dt));
    cx = ncx; cy = ncy;
    const CX = cx * W, CY = cy * H;

    /* 머무름 — 오래 있을수록 붓이 커진다(사용자 지시 2026-07-28:
       "같은 곳에 머무른게 커지면 그 자리가 커지게").
       번짐만으로는 2.25초에 18px 밖에 안 자랐다 — 확산은 퍼지면서 동시에 묽어져
       가장자리가 문턱을 못 넘기 때문이다. 붓 자체를 키우는 쪽이 눈에 보인다.
       빠져나갈 때는 2.5배 빠르게 — 움직이기 시작하면 곧바로 붓이 작아져야
       "긋는 선"이 굵어지지 않는다. */
    const speed = Math.hypot(vx, vy);
    dwell = Math.max(0, Math.min(CFG.dwellMax,
      dwell + (speed < CFG.moveHold ? dt : -dt * 2.5)));
    const Rb = R * (1 + CFG.dwellGain * (dwell / CFG.dwellMax));

    /* ② 밭 — 전체가 어두워지고, 커서 자리에 빛을 바른다 */
    const dec = Math.exp(-CFG.decay * dt);
    for (let i = 0; i < F.length; i++) F[i] *= dec;

    // 완벽한 원 하나가 아니라 느리게 도는 어긋난 덩어리 셋. 멈춰 있어도 일렁인다
    const add = CFG.deposit * dt;
    for (let k = 0; k < 3; k++) {
      const ph = t * (.23 + k * .17) + k * 2.1;
      const off = Rb * (.20 + k * .13);
      const bx = CX + Math.cos(ph) * off, by = CY + Math.sin(ph * 1.31) * off * .8;
      const br = Rb * (1.0 - k * .19);
      const rc = br / CFG.cell;
      const i0 = Math.max(0, Math.floor(bx / CFG.cell - rc)), i1 = Math.min(FW - 1, Math.ceil(bx / CFG.cell + rc));
      const j0 = Math.max(0, Math.floor(by / CFG.cell - rc)), j1 = Math.min(FH - 1, Math.ceil(by / CFG.cell + rc));
      const inv = 1 / (br * br);
      for (let j = j0; j <= j1; j++) {
        const dy = (j + .5) * CFG.cell - by;
        for (let i = i0; i <= i1; i++) {
          const dx = (i + .5) * CFG.cell - bx;
          const q = (dx * dx + dy * dy) * inv;
          if (q > 1) continue;
          const w = 1 - q;                       // 부드럽게 떨어진다
          const idx = j * FW + i;
          const nv = F[idx] + add * w * w;
          F[idx] = nv > 1 ? 1 : nv;              // 포화 — 멈춘 자리가 계속 밝다
        }
      }
    }

    /* ②-b 번짐 — 빛이 옆으로 스며든다. 머문 자리가 시간이 갈수록 넓어지고
       (사용자 지시 2026-07-28: "같은 곳에 머무른게 커지면 그 자리가 커지게"),
       덩어리의 기하학이 뭉개져 원으로 읽힐 여지가 더 줄어든다.
       명시적 확산이라 D·dt ≤ 0.25 를 넘으면 발산한다 — 그래서 한 프레임에 쓸 수
       있는 양을 잘라 둔다. dt 가 튀는 프레임(탭 복귀 직후)에서 화면이 하얗게
       타 버리는 것을 막는 안전장치다. */
    const D = Math.min(CFG.diffuse * dt, 0.24);
    if (D > 1e-4) {
      Fs.set(F);
      for (let j = 1; j < FH - 1; j++) {
        const row = j * FW;
        for (let i = 1; i < FW - 1; i++) {
          const k = row + i;
          F[k] = Fs[k] + D * (Fs[k - 1] + Fs[k + 1] + Fs[k - FW] + Fs[k + FW] - 4 * Fs[k]);
        }
      }
    }

    /* ③ 밭에 감마를 먹여 모티프 마스크로 올린다. 문턱이 높아 아주 밝은 데서만
       드러나므로 한 개가 통째로 뜨지 않고 조금씩 보인다 */
    const db = imgB.data, g = CFG.gMotif;
    for (let i = 0; i < F.length; i++) db[i * 4 + 3] = Math.pow(F[i], g) * 255;
    fbCtx.putImageData(imgB, 0, 0);

    lctx.clearRect(0, 0, W, H);
    if (baked) {
      lctx.globalAlpha = CFG.ink;
      lctx.drawImage(fB, 0, 0, W, H);   // 업스케일 — 부드러운 장이라 티가 안 난다
      lctx.globalAlpha = 1;
      // source-in: 방금 깐 빛의 알파로 잉크를 오려낸다. 결과 알파 = 빛 × 잉크
      lctx.globalCompositeOperation = 'source-in';
      lctx.drawImage(ink, 0, 0);
      lctx.globalCompositeOperation = 'source-over';
    }

    /* ④ 먼지 — 밭의 **기울기**를 타고 밀려난다. 방사 대칭이 아니라 빛이 번진
       모양을 따라 걷히므로 여기서도 원이 나오지 않는다 */
    for (const b of bucket) b.length = 0;
    const push = CFG.push * R, sweep = CFG.sweep, swirl = CFG.swirl * R;
    const NB = CFG.buckets, aTop = CFG.aMax * (1 + CFG.twinkle);
    const hcell = CFG.cell;

    for (const p of dust) {
      // 홈은 가만히 있지 않는다 — 빛이 없어도 아주 느리게 부유한다
      const hx = p.hx + Math.sin(t * p.s1 + p.ph) * CFG.home;
      const hy = p.hy + Math.cos(t * p.s2 + p.ph * 1.7) * CFG.home * .8;

      const w = sample(hx, hy);
      let tgx = hx, tgy = hy;
      if (w > .004) {
        // 기울기는 밝은 쪽을 가리킨다 — 밀어낼 방향은 그 반대다
        const gx = sample(hx + hcell, hy) - sample(hx - hcell, hy);
        const gy = sample(hx, hy + hcell) - sample(hx, hy - hcell);
        const len = Math.hypot(gx, gy);
        let ux, uy;
        if (len > 1e-4) { ux = -gx / len; uy = -gy / len; }
        else { ux = p.ex; uy = p.ey; }          // 한복판 — 기울기가 0 이다
        tgx = hx + (ux * push - uy * swirl + vx * sweep) * w;
        tgy = hy + (uy * push + ux * swirl + vy * sweep) * w;
      }
      // 밀릴 때 빠르고 되메워질 때 느리다. 이 비대칭이 "걷힌다"를 만든다
      const dd = (tgx - hx) * (tgx - hx) + (tgy - hy) * (tgy - hy);
      const cur = (p.x - hx) * (p.x - hx) + (p.y - hy) * (p.y - hy);
      const e = 1 - Math.exp(-(dd > cur ? CFG.kOut : CFG.kIn) * dt);
      p.x += (tgx - p.x) * e;
      p.y += (tgy - p.y) * e;

      // 밝은 자리에서 옅어진다. 이게 없으면 밀린 먼지가 경계에 쌓여 링이 보인다
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
       밭이 비어 있으면 검은 화면만 남으므로, 자율 위치에 빛을 한 번 충분히 발라
       한 프레임으로 구도를 만든다. */
    FINE = false;
    for (let i = 0; i < 30; i++) paint(0, .12);
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

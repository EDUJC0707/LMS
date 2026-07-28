/**
 * 디버그 패널 — ⌘⌥D(맥) / Ctrl+Alt+D 로 연다.
 *
 * index.html 이 단축키를 받으면 그때 처음 import 한다. 열지 않으면 이 파일은
 * 내려받지도 실행되지도 않으므로 실사용자에게는 존재하지 않는 것과 같다.
 *
 * 손잡이를 잡고 아무 데나 끌어다 놓을 수 있고, 가장자리 근처에 놓으면 달라붙는다.
 * 헤더를 누르면 **한 줄로 접힌다** — 화면을 가리지 않고 옆에 놔둘 수 있어야 하고,
 * 접어도 지금 무슨 값인지는 보여야 한다.
 *
 * 노브는 전부 여기 있다. 바꾸면 즉시 반영되고 localStorage 에 남는다.
 * "초기값으로" 는 코드에 박힌 값(BASE)으로 되돌린다.
 */

/* 저장 키에 버전을 붙인다. 기본값이 바뀔 때 키를 올리면 옛 저장값이 자동으로
   버려진다 — 안 그러면 코드를 고쳐도 화면은 옛 값 그대로라 한참 헤맨다. */
const LS = 'hjc-debug-v4';
const clamp = (v, a, b) => (v < a ? a : v > b ? b : v);

/* 코드에 박힌 값. 첫 open 때 한 번만 뜬다 — 닫았다 열 때마다 뜨면 그때의
   조정값이 "초기값"이 돼 버려 영영 원래대로 못 돌아간다. */
let BASE = null;

/* 블루 6종. 전부 에셋에서 나온 청색계이고 색상각(H)과 채도만 다르다.
   에셋 심부 평균이 H236 이라 그걸 가운데 두고 양옆으로 벌렸고,
   **확정은 royal(H224)** 이다(2026-07-28) — 나머지는 되돌려 보기 위해 남긴다.
   accent 휘도를 132 근처로 맞춰 놨다 — 밝기가 제각각이면 "어떤 파랑이 예쁜가"가
   아니라 "어떤 게 밝은가"를 고르게 된다. */
const BLUES = [
  { key: 'royal', name: '로열 (확정)', h: 224,
    dim: '#5E6B9C', accent: '#6B87DE', glow: '#9EAEE1', chip: '#101729', t1: '#606DA4', t2: '#EEF1FA' },
  { key: 'asset', name: '에셋 심부', h: 236,
    dim: '#666999', accent: '#787ED7', glow: '#A5A9DD', chip: '#131427', t1: '#676BA1', t2: '#F0F1FA' },
  { key: 'indigo', name: '인디고', h: 248,
    dim: '#6A6699', accent: '#8578DB', glow: '#ADA5DF', chip: '#151327', t1: '#6D67A3', t2: '#F2F0FA' },
  { key: 'electric', name: '일렉트릭', h: 212,
    dim: '#557099', accent: '#5290E0', glow: '#93B4E2', chip: '#0C1A29', t1: '#5673A4', t2: '#ECF2FA' },
  { key: 'ice', name: '아이스', h: 200,
    dim: '#587490', accent: '#54A0D4', glow: '#95BCD8', chip: '#0B1B26', t1: '#59769B', t2: '#EBF3FA' },
  { key: 'steel', name: '스틸', h: 230,
    dim: '#6B6E85', accent: '#8288B4', glow: '#A8ACC6', chip: '#15161F', t1: '#6E7191', t2: '#F0F0F5' },
];

/* CSS 변수로 나가는 노브의 정의. 키마다 어떤 변수에 어떤 단위로 쓰는지,
   모바일 짝이 있는지를 여기 한 군데에 적는다 — 분기를 apply() 에 흩뿌리면
   변수를 하나 더할 때마다 세 군데를 고쳐야 한다. */
const CSSVARS = {
  h:     { v: '--teacher-h',     sm: '--teacher-h-sm',     smKey: 'hSm', unit: 'svh' },
  r:     { v: '--teacher-right', sm: '--teacher-right-sm', smKey: 'rSm', unit: '%' },
  h1gap: { v: '--h1-gap', unit: 'em' },
};

/* 노브. [키, 라벨, 최소, 최대, 간격, 어디에 쓰나, 소수자리]
   where: 'css' = CSS 변수(강사)
          'cfg' = field.js CFG 에 즉시 대입
          'new' = CFG 대입 + 입자를 다시 만들어야 반영(생성 시점에 읽는 값이라서)
          'fit' = CFG 대입 + fit() 재실행(픽셀로 환산되는 값이라서) */
const GROUPS = [
  ['블루 · 강사', [
    ['h',       '크기',      35, 100, 1,   'css', 0],
    ['r',       '위치',     -25,  35, 1,   'css', 0],
  ]],
  ['먼지', [
    ['dust',    '개수',     200, 4000, 50, 'new', 0],
    ['dMin',    '최소 크기', 0.5,   4, .1, 'new', 1],
    ['dMax',    '최대 크기', 0.5,   6, .1, 'new', 1],
    ['aMin',    '최소 밝기', .01,  .5, .01,'new', 2],
    ['aMax',    '최대 밝기', .02,  .7, .01,'new', 2],
    ['twinkle', '반짝임',      0,   1, .05,'cfg', 2],
    ['home',    '부유 반경',   0,  30, 1,  'cfg', 0],
  ]],
  ['바람', [
    ['R',       '창 반경',   .05, .40, .01,'fit', 2],
    ['push',    '밀어냄',      0,   2, .05,'cfg', 2],
    ['sweep',   '진행 쓸림',   0,  .6, .02,'cfg', 2],
    ['swirl',   '소용돌이',    0,  .8, .02,'cfg', 2],
    ['fade',    '옅어짐',      0,   1, .05,'cfg', 2],
    ['kOut',    '밀림 속도',    1,  20, .5, 'cfg', 1],
    ['kIn',     '되메움 속도', .3,   6, .1, 'cfg', 1],
  ]],
  ['모티프', [
    ['peak',    '최대 밝기', .1,   1, .02,'cfg', 2],
    ['drift',   '부유 반경',  0,  20, 1,  'cfg', 0],
  ]],
  ['헤드라인', [
    ['h1gap',   '줄 간격',    0,  .8, .01,'css', 2],
  ]],
];

const CSS = `
.dbg{
  position:fixed; z-index:9999; width:236px; border-radius:12px;
  background:rgba(11,11,18,.94); backdrop-filter:blur(14px);
  border:1px solid rgba(150,155,220,.20); box-shadow:0 16px 46px rgba(0,0,0,.62);
  color:#DCDEF0; font:12px/1.4 ui-sans-serif,system-ui,"Apple SD Gothic Neo",sans-serif;
  user-select:none; overflow:hidden;
}
.dbg-h{
  display:flex; align-items:center; gap:7px; padding:8px 10px; cursor:grab;
  background:rgba(255,255,255,.05); font-weight:700; letter-spacing:.01em; white-space:nowrap;
}
.dbg-h.drag{ cursor:grabbing }
.dbg-h u{ width:9px; height:9px; border-radius:3px; background:var(--dot,#787ED7); flex:none }
.dbg-h s{ margin-left:auto; color:#767AA0; font:11px ui-monospace,monospace; text-decoration:none }
.dbg-h em{ color:#767AA0; font:12px/1 ui-sans-serif,system-ui; font-style:normal; flex:none }
.dbg-b{ padding:10px; max-height:min(72vh,640px); overflow:auto; overscroll-behavior:contain }
/* 접힘 — 헤더 한 줄만 남는다 */
.dbg.min{ width:auto }
.dbg.min .dbg-b{ display:none }
.dbg.min .dbg-h{ padding:6px 10px; font-size:11px }

.dbg h4{
  margin:13px 0 6px; font-size:10px; font-weight:700; letter-spacing:.09em;
  color:#6E72A0; text-transform:uppercase;
}
.dbg h4:first-child{ margin-top:0 }
.dbg-r{ margin-bottom:7px }
.dbg-r label{ display:flex; color:#8F94BC; font-size:11px; margin-bottom:2px }
.dbg-r label i{ margin-left:auto; font-style:normal; color:#fff; font-variant-numeric:tabular-nums }
.dbg input[type=range]{ width:100%; accent-color:var(--accent,#787ED7); margin:0; display:block; height:14px }
.dbg-sw{ display:flex; gap:4px; margin-bottom:9px }
.dbg-sw button{
  flex:1; height:24px; border-radius:6px; cursor:pointer; padding:0;
  border:1px solid rgba(255,255,255,.14); background:var(--c);
}
.dbg-sw button[aria-pressed=true]{ box-shadow:0 0 0 2px #fff inset, 0 0 0 1px #fff }
.dbg-x{
  width:100%; margin-top:10px; padding:6px; border-radius:7px; cursor:pointer;
  border:1px solid rgba(150,155,220,.20); background:rgba(255,255,255,.05);
  color:#9AA0CC; font:inherit;
}
.dbg-x:hover{ color:#fff; border-color:rgba(150,155,220,.45) }
.dbg-o{
  margin-top:9px; padding:8px; border-radius:7px; background:rgba(0,0,0,.4);
  color:#7E82AC; font:10px/1.5 ui-monospace,monospace;
  white-space:pre-wrap; word-break:break-all; user-select:text; cursor:text;
}
`;

export function openDebug() {
  if (document.querySelector('.dbg')) return null;   // 이미 열려 있다
  const api = window.__field;
  const rootS = document.documentElement.style;
  const sm = () => matchMedia('(max-width: 860px)').matches;

  // index.html 에 박힌 강사 기본값. 여기와 CSS 가 어긋나면 패널을 여는 순간 화면이 튄다
  const TEACHER0 = { h: 80, r: 5, hSm: 40, rSm: -12, h1gap: .14 };
  if (!BASE) BASE = { teacher: { ...TEACHER0 }, blue: 'royal', cfg: api ? { ...api.cfg } : {} };

  const st = document.createElement('style');
  st.textContent = CSS;
  document.head.append(st);

  const el = document.createElement('div');
  el.className = 'dbg';
  el.innerHTML = `<div class="dbg-h"><u></u>디버그<s></s><em>▾</em></div><div class="dbg-b"></div>`;
  const head = el.querySelector('.dbg-h');
  const body = el.querySelector('.dbg-b');
  const dot = head.querySelector('u');
  const stat = head.querySelector('s');
  const caret = head.querySelector('em');

  /* 저장값. 노브 키를 그대로 쓰고, 강사만 데스크탑/모바일이 따로다. */
  const S = Object.assign(
    { blue: 'royal', ...TEACHER0, folded: false },
    JSON.parse(localStorage.getItem(LS) || '{}')
  );
  const save = () => localStorage.setItem(LS, JSON.stringify(S));

  /* ── 노브 만들기 ── */
  const inputs = {};
  for (const [title, rows] of GROUPS) {
    const h4 = document.createElement('h4');
    h4.textContent = title;
    body.append(h4);
    if (title.startsWith('블루')) {
      const sw = document.createElement('div');
      sw.className = 'dbg-sw';
      for (const b of BLUES) {
        const btn = document.createElement('button');
        btn.style.setProperty('--c', b.accent);
        btn.title = `${b.name} · H${b.h}`;
        btn.dataset.key = b.key;
        btn.onclick = () => { S.blue = b.key; apply(); };
        sw.append(btn);
      }
      body.append(sw);
    }
    for (const [key, label, min, max, step, where, dec] of rows) {
      const wrap = document.createElement('div');
      wrap.className = 'dbg-r';
      const lab = document.createElement('label');
      lab.innerHTML = `${label}<i></i>`;
      const inp = document.createElement('input');
      inp.type = 'range'; inp.min = min; inp.max = max; inp.step = step;
      inp.oninput = () => {
        const v = +inp.value, cv = CSSVARS[key];
        S[where === 'css' && cv.sm && sm() ? cv.smKey : key] = v;
        apply(where);
      };
      wrap.append(lab, inp);
      body.append(wrap);
      inputs[key] = { inp, out: lab.querySelector('i'), where, dec };
    }
  }

  const reset = document.createElement('button');
  reset.className = 'dbg-x';
  reset.textContent = '초기값으로';
  const out = document.createElement('div');
  out.className = 'dbg-o';
  body.append(reset, out);

  reset.onclick = () => {
    localStorage.removeItem(LS);
    /* 인라인 변수를 **지운다**. 값만 되돌려 놓으면 :root 인라인이 스타일시트를
       계속 이겨, 나중에 CSS 를 고쳐도 화면이 안 바뀌는 유령이 남는다. */
    for (const k of ['dim', 'accent', 'glow', 'chip', 't1', 't2', 'line',
                     'teacher-h', 'teacher-right', 'teacher-h-sm', 'teacher-right-sm', 'h1-gap'])
      rootS.removeProperty('--' + k);
    Object.assign(S, { blue: BASE.blue, ...BASE.teacher });
    delete S.pos;
    for (const [, rows] of GROUPS)
      for (const [key, , , , , where] of rows) if (where !== 'css') S[key] = BASE.cfg[key];
    if (api) Object.assign(api.cfg, BASE.cfg);
    apply('new');
  };

  /* ── 반영 ── */
  function apply(where) {
    const b = BLUES.find(x => x.key === S.blue) || BLUES[0];
    for (const k of ['dim', 'accent', 'glow', 'chip', 't1', 't2']) rootS.setProperty('--' + k, b[k]);
    // --line 은 accent 에서 파생한다 — 따로 두면 테두리만 다른 파랑이 되는 날이 온다
    const [rr, gg, bb] = [1, 3, 5].map(i => parseInt(b.accent.substr(i, 2), 16));
    rootS.setProperty('--line', `rgba(${rr},${gg},${bb},.26)`);
    body.querySelectorAll('.dbg-sw button')
      .forEach(x => x.setAttribute('aria-pressed', x.dataset.key === S.blue));
    dot.style.setProperty('--dot', b.accent);

    const mob = sm();
    const cssVal = key => { const c = CSSVARS[key]; return S[c.sm && mob ? c.smKey : key]; };
    for (const [key, c] of Object.entries(CSSVARS))
      rootS.setProperty(c.sm && mob ? c.sm : c.v, cssVal(key) + c.unit);

    if (api) {
      for (const [, rows] of GROUPS)
        for (const [key, , , , , w] of rows) {
          if (w === 'css') continue;
          if (S[key] === undefined) S[key] = api.cfg[key];   // 첫 실행 — 코드값을 그대로 물려받는다
          api.cfg[key] = S[key];
        }
      // 최소 > 최대가 되면 rand(a,b) 가 뒤집혀 입자가 통째로 사라진다. 서로 밀어 준다
      if (api.cfg.dMin > api.cfg.dMax) S.dMax = api.cfg.dMax = api.cfg.dMin;
      if (api.cfg.aMin > api.cfg.aMax) S.aMax = api.cfg.aMax = api.cfg.aMin;
      if (where === 'new') api.rebuild(api.cfg.dust);
      else if (where === 'fit') api.refit();
    }

    for (const [key, o] of Object.entries(inputs)) {
      const v = o.where === 'css' ? cssVal(key) : S[key];
      o.inp.value = v;
      o.out.textContent = (+v).toFixed(o.dec) + (o.where === 'css' ? CSSVARS[key].unit : '');
    }

    // 강사 왼쪽 경계 = pack-layout.py 의 모티프 금지선. 옮겼으면 패커를 다시 돌려야 한다
    const tEl = document.querySelector('.teacher');
    const edge = tEl ? (tEl.getBoundingClientRect().left / innerWidth * 100).toFixed(0) : '?';
    stat.textContent = `${b.key}·${mob ? S.hSm : S.h}svh·${edge}%`;
    out.textContent =
`--dim:${b.dim} --accent:${b.accent} --glow:${b.glow}
--chip:${b.chip} --t1:${b.t1} --t2:${b.t2}
.teacher{ right:${mob ? S.rSm : S.r}%; height:${mob ? S.hSm : S.h}svh }
CFG dust:${S.dust} d:${S.dMin}~${S.dMax} a:${S.aMin}~${S.aMax}
    twinkle:${S.twinkle} home:${S.home} peak:${S.peak} drift:${S.drift}
    R:${S.R} push:${S.push} sweep:${S.sweep} swirl:${S.swirl}
    fade:${S.fade} kOut:${S.kOut} kIn:${S.kIn}
pack-layout.py TEACHER_H=${((mob ? S.hSm : S.h) / 100).toFixed(2)} TEACHER_RIGHT=${((mob ? S.rSm : S.r) / 100).toFixed(2)}
  → 강사 왼쪽 경계 ${edge}% (모티프 금지선)`;
    save();
  }
  addEventListener('resize', () => apply());

  /* ── 접기. 접히면 헤더 한 줄만 남고, 그 줄이 지금 값을 말해 준다 ── */
  const fold = v => {
    S.folded = v;
    el.classList.toggle('min', v);
    caret.textContent = v ? '▸' : '▾';
    place();
    save();
  };

  /* ── 끌어 옮기기. 가장자리 24px 안에서 놓으면 달라붙는다 ── */
  const P = S.pos || { x: innerWidth - 236 - 16, y: 16 };
  const place = () => {
    el.style.left = clamp(P.x, 6, Math.max(6, innerWidth - el.offsetWidth - 6)) + 'px';
    el.style.top = clamp(P.y, 6, Math.max(6, innerHeight - el.offsetHeight - 6)) + 'px';
  };
  head.addEventListener('pointerdown', e => {
    const ox = e.clientX - el.offsetLeft, oy = e.clientY - el.offsetTop;
    let moved = false;
    head.classList.add('drag');
    head.setPointerCapture(e.pointerId);
    const move = ev => {
      if (Math.abs(ev.clientX - e.clientX) + Math.abs(ev.clientY - e.clientY) > 3) moved = true;
      P.x = ev.clientX - ox; P.y = ev.clientY - oy; place();
    };
    const up = () => {
      head.classList.remove('drag');
      const SNAP = 24, w = el.offsetWidth, h = el.offsetHeight;
      if (P.x < SNAP) P.x = 6;
      if (P.x + w > innerWidth - SNAP) P.x = innerWidth - w - 6;
      if (P.y < SNAP) P.y = 6;
      if (P.y + h > innerHeight - SNAP) P.y = innerHeight - h - 6;
      place(); S.pos = P; save();
      // 끌지 않고 눌렀다 뗐으면 접기 토글 — 헤더가 손잡이이자 스위치다
      if (!moved) fold(!S.folded);
      head.removeEventListener('pointermove', move);
      head.removeEventListener('pointerup', up);
    };
    head.addEventListener('pointermove', move);
    head.addEventListener('pointerup', up);
  });

  document.body.append(el);
  apply('new');            // 저장값이 없으면 코드값 그대로 — 여는 것만으로 화면이 안 바뀐다
  fold(!!S.folded);
  place();
  return () => { el.remove(); st.remove(); };
}

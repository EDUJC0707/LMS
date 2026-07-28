/**
 * 디버그 패널 — ⌘⌥D 로 연다.
 *
 * index.html 이 단축키를 받으면 그때 처음 import 한다. 열지 않으면 이 파일은
 * 내려받지도 실행되지도 않으므로 실사용자에게는 존재하지 않는 것과 같다.
 *
 * 손잡이를 잡고 아무 데나 끌어다 놓을 수 있다 — 한쪽에 고정돼 있으면 그쪽 화면을
 * 못 보기 때문이다. 가장자리 근처에 놓으면 달라붙고, 위치는 기억한다.
 *
 * **노브는 네 개뿐이다.** 나머지(먼지 크기·반짝임·부유, 밀어냄·쓸림·소용돌이·
 * 되메움 속도)는 값을 정해 코드에 박았다. 눈으로 봐야만 정할 수 있는 것만 남긴다.
 */

const LS = 'hjc-debug';
const clamp = (v, a, b) => (v < a ? a : v > b ? b : v);

/* 블루 6종. 전부 에셋에서 나온 청색계이고 색상각(H)과 채도만 다르다.
   에셋 심부 평균이 H236 이라 그걸 가운데 두고 양옆으로 벌렸다.
   accent 휘도를 132 근처로 맞춰 놨다 — 밝기가 제각각이면 "어떤 파랑이 예쁜가"가
   아니라 "어떤 게 밝은가"를 고르게 된다. */
const BLUES = [
  { key: 'asset', name: '에셋 심부', h: 236,
    dim: '#666999', accent: '#787ED7', glow: '#A5A9DD', chip: '#131427', t1: '#676BA1', t2: '#F0F1FA' },
  { key: 'indigo', name: '인디고', h: 248,
    dim: '#6A6699', accent: '#8578DB', glow: '#ADA5DF', chip: '#151327', t1: '#6D67A3', t2: '#F2F0FA' },
  { key: 'royal', name: '로열', h: 224,
    dim: '#5E6B9C', accent: '#6B87DE', glow: '#9EAEE1', chip: '#101729', t1: '#606DA4', t2: '#EEF1FA' },
  { key: 'electric', name: '일렉트릭', h: 212,
    dim: '#557099', accent: '#5290E0', glow: '#93B4E2', chip: '#0C1A29', t1: '#5673A4', t2: '#ECF2FA' },
  { key: 'ice', name: '아이스', h: 200,
    dim: '#587490', accent: '#54A0D4', glow: '#95BCD8', chip: '#0B1B26', t1: '#59769B', t2: '#EBF3FA' },
  { key: 'steel', name: '스틸', h: 230,
    dim: '#6B6E85', accent: '#8288B4', glow: '#A8ACC6', chip: '#15161F', t1: '#6E7191', t2: '#F0F0F5' },
];

const CSS = `
.dbg{
  position:fixed; z-index:9999; width:250px; border-radius:13px; overflow:hidden;
  background:rgba(12,12,20,.93); backdrop-filter:blur(14px);
  border:1px solid rgba(150,155,220,.20); box-shadow:0 18px 50px rgba(0,0,0,.6);
  color:#DCDEF0; font:12px/1.45 ui-sans-serif,system-ui,"Apple SD Gothic Neo",sans-serif;
  user-select:none;
}
.dbg-h{
  display:flex; align-items:center; gap:8px; padding:9px 11px; cursor:grab;
  background:rgba(255,255,255,.045); border-bottom:1px solid rgba(150,155,220,.14);
  font-weight:700; letter-spacing:.02em;
}
.dbg-h.drag{ cursor:grabbing }
.dbg-h span{ margin-left:auto; color:#767AA0; font-weight:500; font-size:11px }
.dbg-h b{ color:#9AA0CC; font-size:11px; font-weight:600 }
.dbg-b{ padding:11px }
.dbg-r{ margin-bottom:11px }
.dbg-r:last-child{ margin-bottom:0 }
.dbg-r > label{ display:flex; color:#8F94BC; margin-bottom:5px; font-size:11px }
.dbg-r > label i{ margin-left:auto; font-style:normal; color:#fff; font-variant-numeric:tabular-nums }
.dbg input[type=range]{ width:100%; accent-color:var(--accent,#787ED7); margin:0; display:block }
.dbg-sw{ display:flex; gap:5px }
.dbg-sw button{
  flex:1; height:26px; border-radius:7px; cursor:pointer; padding:0;
  border:1px solid rgba(255,255,255,.14); background:var(--c);
}
.dbg-sw button[aria-pressed=true]{ box-shadow:0 0 0 2px #fff inset, 0 0 0 1px #fff }
.dbg-o{
  margin:11px -11px -11px; padding:9px 11px; border-top:1px solid rgba(150,155,220,.14);
  background:rgba(0,0,0,.35); color:#7E82AC; font:10px/1.55 ui-monospace,monospace;
  white-space:pre-wrap; word-break:break-all; user-select:text; cursor:text;
}
`;

export function openDebug() {
  if (document.querySelector('.dbg')) return;   // 이미 열려 있다
  const api = window.__field;

  const st = document.createElement('style');
  st.textContent = CSS;
  document.head.append(st);

  const el = document.createElement('div');
  el.className = 'dbg';
  el.innerHTML = `
    <div class="dbg-h">디버그 <b id="dbgW"></b><span>⌘⌥D</span></div>
    <div class="dbg-b">
      <div class="dbg-r"><label>블루</label><div class="dbg-sw" id="dbgSw"></div></div>
      <div class="dbg-r"><label>강사 크기 <i id="v0"></i></label><input id="s0" type="range" min="35" max="100" step="1"></div>
      <div class="dbg-r"><label>강사 위치 <i id="v1"></i></label><input id="s1" type="range" min="-25" max="35" step="1"></div>
      <div class="dbg-r"><label>먼지 진하기 <i id="v2"></i></label><input id="s2" type="range" min="0" max="100" step="1"></div>
      <div class="dbg-r"><label>바람 크기 <i id="v3"></i></label><input id="s3" type="range" min="6" max="34" step="1"></div>
      <div class="dbg-o" id="dbgOut"></div>
    </div>`;
  document.body.append(el);

  const $ = id => el.querySelector('#' + id);
  const rootS = document.documentElement.style;
  const sm = () => matchMedia('(max-width: 860px)').matches;

  /* 저장값. 기본값은 index.html·field.js 에 박혀 있는 현재 값이다 */
  const S = Object.assign(
    { blue: 'asset', h: 73, hSm: 36, r: 9, rSm: -14, dust: 55, wind: 15 },
    JSON.parse(localStorage.getItem(LS) || '{}')
  );
  const save = () => localStorage.setItem(LS, JSON.stringify(S));

  const sw = $('dbgSw');
  for (const b of BLUES) {
    const btn = document.createElement('button');
    btn.style.setProperty('--c', b.accent);
    btn.title = `${b.name} · H${b.h}`;
    btn.dataset.key = b.key;
    btn.onclick = () => { S.blue = b.key; apply(); };
    sw.append(btn);
  }

  /* 먼지 "진하기" 한 축이 개수와 밝기를 같이 움직인다. 둘을 따로 두면 노브가
     늘어나기만 하고, 실제로 사람이 보는 건 "얼마나 자글자글한가" 하나다. */
  const dustOf = t => ({ n: Math.round(400 + t * 22), a: 0.12 + t * 0.0030 });

  function apply() {
    const b = BLUES.find(x => x.key === S.blue) || BLUES[0];
    for (const k of ['dim', 'accent', 'glow', 'chip', 't1', 't2']) rootS.setProperty('--' + k, b[k]);
    // --line 은 accent 에서 파생한다 — 따로 두면 테두리만 다른 파랑이 되는 날이 온다
    const [rr, gg, bb] = [1, 3, 5].map(i => parseInt(b.accent.substr(i, 2), 16));
    rootS.setProperty('--line', `rgba(${rr},${gg},${bb},.26)`);
    [...sw.children].forEach(x => x.setAttribute('aria-pressed', x.dataset.key === S.blue));

    const mob = sm();
    rootS.setProperty(mob ? '--teacher-h-sm' : '--teacher-h', (mob ? S.hSm : S.h) + 'svh');
    rootS.setProperty(mob ? '--teacher-right-sm' : '--teacher-right', (mob ? S.rSm : S.r) + '%');

    const d = dustOf(S.dust);
    if (api) {
      api.cfg.aMin = +(d.a * 0.55).toFixed(3);
      api.cfg.aMax = +d.a.toFixed(3);
      api.cfg.R = S.wind / 100;
      api.rebuild(d.n);                 // 개수·밝기는 입자 생성 시점 값이라 다시 만든다
    }

    $('v0').textContent = (mob ? S.hSm : S.h) + 'svh';
    $('v1').textContent = (mob ? S.rSm : S.r) + '%';
    $('v2').textContent = `${d.n}개 · ${d.a.toFixed(2)}`;
    $('v3').textContent = (S.wind / 100).toFixed(2);
    $('s0').value = mob ? S.hSm : S.h;
    $('s1').value = mob ? S.rSm : S.r;
    $('s2').value = S.dust;
    $('s3').value = S.wind;
    $('dbgW').textContent = `${innerWidth}×${innerHeight}${mob ? ' 모바일' : ''}`;

    // 강사 왼쪽 경계 = pack-layout.py 의 모티프 금지선. 강사를 옮겼으면 다시 돌려야 한다
    const t = document.querySelector('.teacher');
    const edge = t ? (t.getBoundingClientRect().left / innerWidth * 100).toFixed(0) : '?';
    $('dbgOut').textContent =
`--dim:${b.dim} --accent:${b.accent}
--glow:${b.glow} --chip:${b.chip}
--t1:${b.t1} --t2:${b.t2}
.teacher{ right:${mob ? S.rSm : S.r}%; height:${mob ? S.hSm : S.h}svh }
CFG dust:${d.n} aMax:${d.a.toFixed(2)} R:${(S.wind / 100).toFixed(2)}
pack-layout.py TEACHER_H=${((mob ? S.hSm : S.h) / 100).toFixed(2)} TEACHER_RIGHT=${((mob ? S.rSm : S.r) / 100).toFixed(2)} → 경계 ${edge}%`;
    save();
  }

  const keys = [['s0', v => { sm() ? S.hSm = v : S.h = v; }], ['s1', v => { sm() ? S.rSm = v : S.r = v; }],
                ['s2', v => { S.dust = v; }], ['s3', v => { S.wind = v; }]];
  for (const [id, set] of keys) $(id).oninput = e => { set(+e.target.value); apply(); };
  addEventListener('resize', apply);

  /* ── 끌어 옮기기. 가장자리 24px 안에서 놓으면 달라붙는다 ── */
  const P = S.pos || { x: innerWidth - 250 - 16, y: 16 };
  const place = () => {
    el.style.left = clamp(P.x, 6, innerWidth - el.offsetWidth - 6) + 'px';
    el.style.top = clamp(P.y, 6, innerHeight - el.offsetHeight - 6) + 'px';
  };
  const head = el.querySelector('.dbg-h');
  head.addEventListener('pointerdown', e => {
    const ox = e.clientX - el.offsetLeft, oy = e.clientY - el.offsetTop;
    head.classList.add('drag');
    head.setPointerCapture(e.pointerId);
    const move = ev => { P.x = ev.clientX - ox; P.y = ev.clientY - oy; place(); };
    const up = () => {
      head.classList.remove('drag');
      const SNAP = 24, w = el.offsetWidth, h = el.offsetHeight;
      if (P.x < SNAP) P.x = 6;
      if (P.x + w > innerWidth - SNAP) P.x = innerWidth - w - 6;
      if (P.y < SNAP) P.y = 6;
      if (P.y + h > innerHeight - SNAP) P.y = innerHeight - h - 6;
      place(); S.pos = P; save();
      head.removeEventListener('pointermove', move);
      head.removeEventListener('pointerup', up);
    };
    head.addEventListener('pointermove', move);
    head.addEventListener('pointerup', up);
  });

  apply();
  place();
  return () => { el.remove(); st.remove(); };
}

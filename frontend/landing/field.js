/**
 * 히어로 배경에 숨은 통합과학 개념들.
 *
 * 평상시 완전히 보이지 않는다 — 힌트도 흔적도 깔지 않는다. 방문자가 화면을
 * 만져본다는 전제이고, "여기 뭐가 있어요" 하는 안내를 두는 순간 발견이 아니게 된다.
 * 그래서 뜨는 것도 에셋 하나뿐이다. 라벨·툴팁·설명을 붙이지 않는다.
 */

/* 텍스트·강사 사진을 피해 6개를 흩어놓는다. 값은 히어로 기준 %.
   피해야 할 곳 둘 —
   ① 헤드라인: 좌측 4~36% × 40~64% (검은 화면의 유일한 글자라 조금만 겹쳐도 티가 난다)
   ② 강사: 우측 72%~ 전 높이 */
const LAYOUT = [
  { x: 16, y: 20, size: 18 },   // 헤드라인 위
  { x: 43, y: 14, size: 15 },
  { x: 62, y: 26, size: 17 },
  { x: 12, y: 80, size: 16 },   // 헤드라인 아래
  { x: 50, y: 55, size: 20 },   // 헤드라인 우측 — 글자 끝에서 충분히 떨어뜨린다
  { x: 66, y: 84, size: 14 },
];

/* 모바일은 헤드라인이 화면 한가운데에 오고(1단 배치) 강사가 우하단을 먹는다.
   그래서 세로로 비는 구간은 상단 8~30%와 중하단 55~72% 둘뿐이다.
   그 두 띠에만 놓는다 — 데스크탑 좌표를 그대로 쓰면 글자를 정면으로 덮는다. */
const LAYOUT_SM = [
  { x: 20, y: 11, size: 27 },
  { x: 56, y: 8, size: 21 },
  { x: 84, y: 19, size: 23 },
  { x: 15, y: 58, size: 24 },
  { x: 44, y: 68, size: 25 },
  { x: 22, y: 84, size: 19 },   // 우측 하단은 강사 머리라 좌하단으로
];

const isSmall = () => matchMedia('(max-width: 860px)').matches;

export function mountField(root, units) {
  const spots = units.slice(0, LAYOUT.length).map((u, i) => {
    const el = document.createElement('div');
    el.className = 'spot';
    el.dataset.i = String(i);

    const img = document.createElement('img');
    img.src = u.asset;
    img.alt = '';
    img.decoding = 'async';
    // 지금 안 보이지만 만졌을 때 바로 떠야 한다. 늦게 로드되면 발견이 김샌다.
    img.loading = 'eager';
    el.append(img);
    root.append(el);
    return el;
  });

  const place = () => {
    const L = isSmall() ? LAYOUT_SM : LAYOUT;
    spots.forEach((el, i) => {
      const p = L[i];
      el.style.left = p.x + '%';
      el.style.top = p.y + '%';
      el.style.setProperty('--size', p.size + 'vw');
    });
  };
  place();
  addEventListener('resize', place);

  /* spot에 직접 hover를 걸 수 없다 — 투명한 요소라 판정이 좁고, 큰 히트박스를 깔면
     텍스트·로그인 버튼을 덮는다. 그래서 히어로 전체의 포인터 위치로 거리를 잰다.

     입력 방식은 마운트 시점의 미디어쿼리가 아니라 **이벤트마다 pointerType으로**
     가른다. `(hover: hover)`는 터치 겸용 노트북에서도 참이라, 한 번 분기해두면
     그런 기기에서 탭이 죽는다. */
  const hero = root.parentElement;
  const nearest = (x, y, slack) => {
    let hit = null, best = Infinity;
    for (const el of spots) {
      const r = el.getBoundingClientRect();
      const d = Math.hypot(x - (r.left + r.width / 2), y - (r.top + r.height / 2));
      const reach = Math.max(slack, r.width * 0.62);
      if (d < reach && d < best) { best = d; hit = el; }
    }
    return hit;
  };

  /* 커서 — 가까이 가면 뜨고 멀어지면 꺼진다 */
  let raf = 0, mx = 0, my = 0;
  const paint = () => {
    raf = 0;
    const hit = nearest(mx, my, 150);
    spots.forEach(el => el.classList.toggle('on', el === hit));
  };
  hero.addEventListener('pointermove', e => {
    if (e.pointerType === 'touch') return;      // 탭 뒤에 따라오는 합성 이동 무시
    mx = e.clientX; my = e.clientY;
    if (!raf) raf = requestAnimationFrame(paint);
  });
  hero.addEventListener('pointerleave', e => {
    if (e.pointerType === 'touch') return;
    spots.forEach(el => el.classList.remove('on'));
  });

  /* 터치 — 탭하면 켜지고 한 번 더 탭하면 꺼진다.
     커서처럼 머무는 게 없으므로 스스로 사라지지 않게 두고, 빈 곳을 탭하면 전부 닫는다. */
  hero.addEventListener('pointerdown', e => {
    if (e.pointerType !== 'touch') return;
    const hit = nearest(e.clientX, e.clientY, 120);
    if (hit) hit.classList.toggle('on');
    else spots.forEach(el => el.classList.remove('on'));
  }, { passive: true });
}

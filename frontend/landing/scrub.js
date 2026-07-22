/**
 * 스크롤 스크러빙 엔진 — 프레임 시퀀스를 스크롤 진행률에 매핑한다.
 *
 * 왜 <img> 교체나 전량 프리로드가 아닌가:
 *   실측상 1600px 프레임의 디코드 RGBA는 약 3MB다. 96장을 전부 메모리에 상주시키면
 *   300MB에 육박해 아이패드(PRD §4 — 학생·학부모 1순위 기기)에서 탭이 죽는다.
 *   파일 용량(96장 ≈ 2.7MB)은 논점이 아니다. 상한은 디코드 메모리다.
 *
 * 그래서:
 *   - 캔버스 1개에 그린다 (DOM 노드 96개를 만들지 않는다)
 *   - 현재 프레임 주변만 디코드해 들고 있고, 창을 벗어나면 놓아준다 (슬라이딩 윈도)
 *   - 디코드는 createImageBitmap으로 워커 스레드에 맡겨 메인 스레드를 막지 않는다
 *   - 스크롤 이벤트마다 그리지 않고 rAF에서 한 번만 그린다
 */

const clamp = (v, a, b) => (v < a ? a : v > b ? b : v);

export class ScrubSequence {
  /**
   * @param {object} opt
   * @param {HTMLCanvasElement} opt.canvas   그릴 캔버스
   * @param {(i:number)=>string} opt.src     프레임 인덱스 → URL
   * @param {number} opt.count               총 프레임 수
   * @param {HTMLElement} opt.track          스크롤 진행률을 재는 기준 엘리먼트(보통 sticky 부모)
   * @param {number} [opt.window=12]         현재 프레임 앞뒤로 유지할 디코드 개수
   * @param {number} [opt.eager=8]           최초에 미리 디코드할 개수
   * @param {(p:number)=>void} [opt.onProgress] 진행률 콜백 (0~1) — 텍스트 페이드 등에 쓴다
   */
  constructor(opt) {
    this.canvas = opt.canvas;
    this.ctx = this.canvas.getContext('2d', { alpha: false });
    this.src = opt.src;
    this.count = opt.count;
    this.track = opt.track;
    this.win = opt.window ?? 12;
    this.eager = opt.eager ?? 8;
    this.onProgress = opt.onProgress;
    // 소스 프레임은 좌측 배치로 생성됐다(우측에 텍스트를 얹던 시절 규칙).
    // 순수 애니메이션으로 시작하는 지금은 주인공이 중앙에 와야 하므로
    // 그리기 원점을 오른쪽으로 밀어 보정한다. 값은 캔버스 폭 대비 비율.
    this.offsetX = opt.offsetX ?? 0;
    this.fill = opt.fill ?? '#000';

    this.bitmaps = new Map();   // index → ImageBitmap
    this.pending = new Map();   // index → Promise
    this.current = -1;
    this.progress = 0;
    this.queued = false;
    this.destroyed = false;

    this._onScroll = () => this._request();
    // 캔버스 크기를 바꾸면 내용이 지워진다. _tick()은 인덱스가 그대로면 다시 그리지 않으므로
    // 리사이즈 직후에는 현재 프레임을 강제로 한 번 더 그려야 화면이 검게 남지 않는다.
    this._onResize = () => { this._fit(); this._redraw(); this._request(); };
  }

  async start() {
    this._fit();
    // 첫 프레임은 반드시 그려져 있어야 한다 — 빈 캔버스로 시작하면 '로딩 실패'로 읽힌다.
    await this._ensure(0);
    this._draw(0);
    for (let i = 1; i < Math.min(this.eager, this.count); i++) this._ensure(i);

    addEventListener('scroll', this._onScroll, { passive: true });
    addEventListener('resize', this._onResize);
    this._request();
  }

  destroy() {
    this.destroyed = true;
    removeEventListener('scroll', this._onScroll);
    removeEventListener('resize', this._onResize);
    for (const b of this.bitmaps.values()) b.close?.();
    this.bitmaps.clear();
    this.pending.clear();
  }

  _fit() {
    // 레티나에서 흐려지지 않게 하되, DPR 3짜리 기기에서 캔버스가 과대해지지 않도록 2로 묶는다.
    const dpr = Math.min(devicePixelRatio || 1, 2);
    const r = this.canvas.getBoundingClientRect();
    this.canvas.width = Math.round(r.width * dpr);
    this.canvas.height = Math.round(r.height * dpr);
  }

  /** track이 화면을 지나간 비율 0~1 */
  _measure() {
    const r = this.track.getBoundingClientRect();
    const total = r.height - innerHeight;
    if (total <= 0) return 0;
    return clamp(-r.top / total, 0, 1);
  }

  _request() {
    if (this.queued || this.destroyed) return;
    this.queued = true;
    requestAnimationFrame(() => {
      this.queued = false;
      this._tick();
    });
  }

  _tick() {
    const p = this._measure();
    this.progress = p;
    this.onProgress?.(p);

    const idx = clamp(Math.round(p * (this.count - 1)), 0, this.count - 1);
    if (idx !== this.current) {
      // 있으면 즉시 그리고, 없으면 디코드를 걸어두되 마지막 프레임을 유지한다.
      // 빈 화면을 내는 것보다 한 프레임 늦는 편이 낫다.
      if (this.bitmaps.has(idx)) this._draw(idx);
      else this._ensure(idx).then(() => { if (!this.destroyed && this._nearest() === idx) this._draw(idx); });

      this._prefetch(idx);
      this._evict(idx);
    }
  }

  _nearest() {
    return clamp(Math.round(this.progress * (this.count - 1)), 0, this.count - 1);
  }

  /** 인덱스를 바꾸지 않고 현재 프레임만 다시 그린다 (리사이즈 복구용) */
  _redraw() {
    if (this.current >= 0 && this.bitmaps.has(this.current)) {
      const keep = this.current;
      this.current = -1;      // _draw가 current를 다시 세팅하므로 잠깐 풀어준다
      this._draw(keep);
    }
  }

  _draw(i) {
    const bmp = this.bitmaps.get(i);
    if (!bmp) return;
    const { width: cw, height: ch } = this.canvas;
    // cover 피팅 — 히어로를 꽉 채우고 넘치는 쪽을 잘라낸다.
    const s = Math.max(cw / bmp.width, ch / bmp.height);
    const w = bmp.width * s, h = bmp.height * s;
    const dx = this.offsetX * cw;
    if (dx) {
      // 오른쪽으로 밀면 왼쪽에 빈 띠가 생긴다. 프레임 배경이 단색이므로
      // 같은 색으로 채우면 이어져 보인다.
      this.ctx.fillStyle = this.fill;
      this.ctx.fillRect(0, 0, cw, ch);
    }
    this.ctx.drawImage(bmp, (cw - w) / 2 + dx, (ch - h) / 2, w, h);
    this.current = i;
  }

  _ensure(i) {
    if (this.bitmaps.has(i)) return Promise.resolve();
    if (this.pending.has(i)) return this.pending.get(i);
    const job = fetch(this.src(i))
      .then(r => r.blob())
      .then(b => createImageBitmap(b))   // 디코드를 메인 스레드 밖으로
      .then(bmp => {
        if (this.destroyed) { bmp.close?.(); return; }
        this.bitmaps.set(i, bmp);
      })
      .catch(() => { /* 한 장 실패해도 시퀀스를 멈추지 않는다 */ })
      .finally(() => this.pending.delete(i));
    this.pending.set(i, job);
    return job;
  }

  /** 진행 방향 쪽을 더 많이 당겨온다 */
  _prefetch(i) {
    const fwd = i >= this.current;
    const ahead = Math.ceil(this.win * 0.7), back = this.win - ahead;
    const lo = fwd ? i - back : i - ahead;
    const hi = fwd ? i + ahead : i + back;
    for (let k = lo; k <= hi; k++) {
      if (k >= 0 && k < this.count) this._ensure(k);
    }
  }

  /** 창 밖은 놓아준다 — 이게 없으면 스크롤을 끝까지 내린 시점에 전량이 상주한다 */
  _evict(i) {
    const keep = this.win + 4;
    for (const [k, bmp] of this.bitmaps) {
      if (Math.abs(k - i) > keep) {
        bmp.close?.();          // close()가 있어야 GC를 기다리지 않고 즉시 해제된다
        this.bitmaps.delete(k);
      }
    }
  }
}

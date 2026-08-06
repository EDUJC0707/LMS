/* 진짜 터치 기기로 위장해 페이지를 재고 찍는다.
 *
 * 왜 필요한가: Playwright MCP 의 브라우저는 뷰포트를 390px 로 줄여도
 * `pointer: fine` / `hover: hover` 를 보고한다. 그래서 `(hover:none) and
 * (pointer:coarse)` 분기(field.js 의 COARSE)를 **절대 못 탄다** — 모바일을 본다고
 * 믿으면서 데스크탑 경로를 찍게 된다. CDP 의 Emulation.setDeviceMetricsOverride
 * ({mobile:true}) + setTouchEmulationEnabled 은 그 미디어 쿼리까지 실제로 바꾼다.
 *
 * 그리고 MCP 브라우저는 프로필 하나를 직렬로 쓰기 때문에 에이전트 여럿이 붙으면
 * 서로를 막는다(2026-08-05 에 실제로 전원이 잠겨 워크플로 하나를 폐기했다).
 * 이 스크립트는 매번 제 크롬을 띄우므로 병렬로 돌려도 안전하다.
 *
 * 사용:
 *   node touchprobe.mjs --url <URL> [옵션]
 *     --out <파일.png>     스크린샷 저장 (생략하면 안 찍는다)
 *     --full               전체 페이지 찍기 (기본은 뷰포트만)
 *     --w <390> --h <844>  뷰포트 (기본 390x844)
 *     --dpr <3>            기기 픽셀비 (기본 3)
 *     --wait <2500>        평가 전 대기 ms
 *     --scroll <px>        평가 전 스크롤
 *     --desktop            터치 위장을 끈다(데스크탑 대조군용, 기본 1200x800)
 *     --eval '<식>'        페이지에서 평가할 JS. 반환값을 JSON 으로 찍는다.
 *                          여러 번 줄 수 있다.
 *
 * 예:
 *   node touchprobe.mjs --url http://localhost:4174/landing/index.html \
 *     --eval "getComputedStyle(document.querySelector('h1')).fontSize" \
 *     --eval "document.body.scrollWidth > innerWidth"
 */
import { spawn } from 'node:child_process';
import { writeFileSync, existsSync } from 'node:fs';

const A = process.argv.slice(2);
const arg = (k, d) => { const i = A.indexOf(k); return i < 0 ? d : A[i + 1]; };
const has = k => A.includes(k);
const evals = A.reduce((a, v, i) => (v === '--eval' ? [...a, A[i + 1]] : a), []);

const DESKTOP = has('--desktop');
const W = +arg('--w', DESKTOP ? 1200 : 390);
const H = +arg('--h', DESKTOP ? 800 : 844);
const DPR = +arg('--dpr', DESKTOP ? 2 : 3);
const WAIT = +arg('--wait', 2500);
const SCROLL = +arg('--scroll', 0);
const URL_ = arg('--url');
const OUT = arg('--out');
if (!URL_) { console.error('--url 이 필요하다'); process.exit(2); }

const CANDIDATES = [
  '/Users/seanpark/Library/Caches/ms-playwright/chromium-1234/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing',
  '/Users/seanpark/Library/Caches/ms-playwright/chromium-1208/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing',
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
];
const CH = CANDIDATES.find(existsSync);
if (!CH) { console.error('크롬을 못 찾았다'); process.exit(2); }

const PORT = 9000 + (process.pid % 900);
const DIR = `/tmp/cdp-${process.pid}-${Date.now()}`;
const chrome = spawn(CH, [
  '--headless=new', '--disable-gpu', '--hide-scrollbars', '--mute-audio',
  `--remote-debugging-port=${PORT}`, `--user-data-dir=${DIR}`,
  '--no-first-run', '--no-default-browser-check', 'about:blank',
], { stdio: 'ignore' });

const sleep = ms => new Promise(r => setTimeout(r, ms));
let ws, id = 0; const pending = new Map();
const send = (method, params = {}) => new Promise((res, rej) => {
  const n = ++id; pending.set(n, { res, rej });
  ws.send(JSON.stringify({ id: n, method, params }));
  setTimeout(() => pending.has(n) && (pending.delete(n), rej(new Error(method + ' 시간 초과'))), 30000);
});

try {
  let target = null;
  for (let i = 0; i < 80 && !target; i++) {
    await sleep(250);
    try {
      const r = await fetch(`http://127.0.0.1:${PORT}/json/list`);
      target = (await r.json()).find(t => t.type === 'page');
    } catch {}
  }
  if (!target) throw new Error('CDP 포트가 안 열림');

  ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((r, j) => { ws.onopen = r; ws.onerror = () => j(new Error('ws 연결 실패')); });
  ws.onmessage = e => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) {
      const { res, rej } = pending.get(m.id); pending.delete(m.id);
      m.error ? rej(new Error(m.error.message)) : res(m.result);
    }
  };

  await send('Page.enable'); await send('Runtime.enable');
  await send('Emulation.setDeviceMetricsOverride',
    { width: W, height: H, deviceScaleFactor: DPR, mobile: !DESKTOP });
  if (!DESKTOP) {
    await send('Emulation.setTouchEmulationEnabled', { enabled: true, maxTouchPoints: 5 });
    await send('Emulation.setEmitTouchEventsForMouse', { enabled: true, configuration: 'mobile' });
  }

  // --reduce : prefers-reduced-motion:reduce 로 위장한다. 이 분기는 rAF 를 안 돌리고
  // 정적 1프레임만 그리므로, 켜고 재지 않으면 그 경로가 통째로 미검증으로 남는다.
  if (has('--reduce')) {
    await send('Emulation.setEmulatedMedia', {
      features: [{ name: 'prefers-reduced-motion', value: 'reduce' }],
    });
  }

  await send('Page.navigate', { url: URL_ });
  await sleep(WAIT);
  if (SCROLL) {
    await send('Runtime.evaluate', { expression: `scrollTo(0,${SCROLL})` });
    await sleep(600);
  }

  const env = await send('Runtime.evaluate', {
    returnByValue: true,
    expression: `JSON.stringify({vw:innerWidth,vh:innerHeight,dpr:devicePixelRatio,
      coarse:matchMedia('(hover: none) and (pointer: coarse)').matches,
      touchPts:navigator.maxTouchPoints})`,
  });
  console.log('ENV ' + env.result.value);

  for (const ex of evals) {
    try {
      const r = await send('Runtime.evaluate', {
        /* async IIFE 로 감싸고 await 한다. 그냥 JSON.stringify 하면 Promise 가
           `{}` 로 찍혀 아무것도 안 나온 것처럼 보인다 — 실제로 한 번 당했다.
           동기 식도 await 를 통과하므로 둘 다 이 한 형태로 처리된다. */
        expression: `(async()=>{try{return JSON.stringify(await (${ex}))}catch(e){return 'ERR '+e.message}})()`,
        returnByValue: true, awaitPromise: true,
      });
      console.log('EVAL ' + r.result.value);
    } catch (e) { console.log('EVAL ERR ' + e.message); }
  }

  if (OUT) {
    let opt = { format: 'png' };
    if (has('--full')) {
      const m = await send('Page.getLayoutMetrics');
      const cs = m.cssContentSize || m.contentSize;
      opt.clip = { x: 0, y: 0, width: cs.width, height: cs.height, scale: 1 };
      opt.captureBeyondViewport = true;
    }
    const s = await send('Page.captureScreenshot', opt);
    writeFileSync(OUT, Buffer.from(s.data, 'base64'));
    console.log('SHOT ' + OUT);
  }
} catch (e) {
  console.log('FAIL ' + e.message);
  process.exitCode = 1;
} finally {
  try { ws?.close(); } catch {}
  chrome.kill('SIGKILL');
}

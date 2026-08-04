/**
 * 채널톡.
 *
 * 랜딩의 1차 목적이 상담 전환인데(PRD §3.3.3) 히어로에 CTA를 두지 않는다.
 * 그 역할을 이 위젯이 상시 부유하며 대신한다. 그래서 여기가 유일한 전환 경로다.
 *
 * 플러그인 키는 배포 시 주입한다. 키가 없으면 위젯을 띄우지 않고,
 * 버튼은 눌러도 아무 일이 없는 대신 콘솔에 이유를 남긴다 — 조용히 죽는 것보다 낫다.
 */

/* trim 하는 이유: 이 값은 사람이 index.html 에 손으로 붙여 넣는다. 공백만 남거나
   붙여넣기에 줄바꿈이 딸려 오면, 그대로 부팅해서 엉뚱한 키로 CDN 요청이 나간다. */
const PLUGIN_KEY = (window.__CHANNEL_TALK_KEY__ || '').trim();

function boot() {
  if (!PLUGIN_KEY) return false;
  /* 공식 부트 스크립트 (channel.io) */
  (function () {
    const w = window;
    if (w.ChannelIO) return;
    const ch = function () { ch.c(arguments); };
    ch.q = [];
    ch.c = args => ch.q.push(args);
    w.ChannelIO = ch;
    const s = document.createElement('script');
    s.async = true;
    s.src = 'https://cdn.channel.io/plugin/ch-plugin-web.js';
    document.head.appendChild(s);
  })();
  window.ChannelIO('boot', { pluginKey: PLUGIN_KEY });
  return true;
}

const ready = boot();

/**
 * 문의창을 연다.
 * @param {string} [context] 어디서 눌렀는지 — 상담 맥락을 미리 채워준다
 */
export function openChat(context) {
  if (!ready || !window.ChannelIO) {
    console.info('[chat] 채널톡 키가 없어 위젯을 띄우지 않았다. context:', context);
    return;
  }
  if (context) window.ChannelIO('setPage', location.pathname + '#' + context);
  window.ChannelIO('showMessenger');
}

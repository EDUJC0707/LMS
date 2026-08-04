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
 *
 * 맥락을 넘기는 길이 둘인데 하는 일이 다르다 —
 * `setPage` 는 상담이 생길 때 붙는 페이지 값이라 **상담원 화면에** 남고,
 * 입력창을 실제로 채우는 것은 `openChat` 의 셋째 인자다(SPEC §7-3 의 "프리필").
 * 그래서 둘 다 부른다. `chatId` 를 비우면 새 상담이 열린다.
 *
 * @param {string} [context] 어디서 눌렀는지 — `data-chat` 값이 그대로 온다
 */
export function openChat(context) {
  if (!ready || !window.ChannelIO) {
    console.info('[chat] 채널톡 키가 없어 위젯을 띄우지 않았다. context:', context);
    return;
  }
  /* 채울 말이 없으면 새 상담을 강제로 열지 않는다 — 진행 중이던 상담이 갈린다. */
  if (!context) {
    window.ChannelIO('showMessenger');
    return;
  }
  window.ChannelIO('setPage', location.pathname + '#' + context);
  window.ChannelIO('openChat', undefined, context);
}

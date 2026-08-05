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

/* 부팅이 실패했는지. 위 주석의 "조용히 죽지 않는다" 는 이 값 없이는 못 지킨다 —
   부트 스텁이 window.ChannelIO 를 먼저 세우기 때문에, CDN 이 막혀도 스텁은 남아
   호출이 큐에만 쌓이고 버튼은 무반응이 된다. 실패를 따로 기억해야 알 수 있다. */
let failed = false;

function fail(why, detail) {
  failed = true;
  console.info('[chat] ' + why, detail ?? '');
}

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
    s.onerror = () => fail('채널톡 스크립트를 받지 못했다.');
    document.head.appendChild(s);
  })();
  /* language 를 안 넘기면 채널톡은 navigator.language 를 따른다(번들 getLanguage 실측).
     이 페이지는 lang="ko" 에 카피가 전부 한국어인데, 영어로 맞춰 둔 아이패드에서는
     그 위에 영어 메신저가 뜬다 — 학생·학부모 1순위 기기가 아이패드다(PRD §4). */
  /* 런처가 좁은 화면에서 강사 사진 위에 겹친다 — 390x844 에서 런처 사각형
     (56x56, 오른쪽아래 24px 안쪽)이 강사 바운딩박스 안에 100% 들어간다.
     데스크탑에서는 같은 자리가 인물 오른쪽 바깥이라 안 겹친다.

     **로드하자마자 보인다**(2026-08-06 사용자 지시). `hideChannelButtonOnBoot` 로
     히어로를 지나갈 때까지 미루는 안을 만들었다가 되돌렸다 — 랜딩의 유일한 전환
     경로라 처음부터 보이는 쪽이 맞다.

     겹침은 코드가 아니라 채널톡 관리자에서 위치·크기로 푼다(대표 담당).
     웹 SDK 부트 옵션에는 위치·여백 필드가 없다(문서 확인) — 여기서 할 수 있는
     일이 애초에 없다. */
  window.ChannelIO('boot', { pluginKey: PLUGIN_KEY, language: 'ko' }, err => {
    if (err) fail('채널톡 부팅에 실패했다.', err);
  });
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
  if (!ready) {
    console.info('[chat] 채널톡 키가 없어 위젯을 띄우지 않았다. context:', context);
    return;
  }
  if (failed || !window.ChannelIO) {
    console.info('[chat] 채널톡이 떠 있지 않아 문의창을 열지 못했다. context:', context);
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

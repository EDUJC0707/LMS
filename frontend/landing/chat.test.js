/**
 * chat.js 계약.
 *
 * 여기서 지키는 것은 하나다 — **키가 서기 전까지 랜딩은 아무 일도 하지 않는다.**
 * 채널톡이 랜딩의 유일한 전환 경로라(PRD 3.3.3) 키가 오면 바로 붙어야 하고,
 * 오기 전까지는 CDN 요청도 콘솔 에러도 없어야 한다.
 *
 * chat.js 는 브라우저 모듈이라 window·document 를 세워 두고 읽힌다.
 * 키를 **모듈 로드 시점에** 읽으므로 케이스마다 캐시를 깨서 다시 import 한다.
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';

let seq = 0;

async function loadChat(key) {
  const appended = [];
  globalThis.window = key === undefined ? {} : { __CHANNEL_TALK_KEY__: key };
  globalThis.document = {
    head: { appendChild: el => appended.push(el) },
    createElement: () => ({}),
  };
  globalThis.location = { pathname: '/랜딩' };

  const { openChat } = await import(`./chat.js?case=${++seq}`);
  return {
    openChat,
    appended,
    /** boot() 이 심어 둔 큐 — CDN 스크립트가 안 오므로 호출이 여기 쌓인다. */
    calls: () => Array.from(globalThis.window.ChannelIO?.q ?? [], a => Array.from(a)),
  };
}

/** console 을 통째로 붙잡는다 — info 는 세고, error·warn 은 한 줄도 나오면 안 된다. */
function capture(fn) {
  const out = { info: [], warn: [], error: [] };
  const real = { info: console.info, warn: console.warn, error: console.error };
  for (const k of Object.keys(out)) console[k] = (...a) => out[k].push(a.map(String).join(' '));
  try { fn(); } finally { Object.assign(console, real); }
  return out;
}

test('공백뿐인 키는 키가 없는 것으로 본다', async () => {
  const chat = await loadChat('   ');

  assert.deepEqual(chat.appended, [], '채널톡 스크립트를 내려받으면 안 된다');
  assert.deepEqual(chat.calls(), [], 'boot 을 부르면 안 된다');
});

test('키 앞뒤 공백은 떼고 부팅한다', async () => {
  const chat = await loadChat('  pk-abc123\n');

  assert.deepEqual(chat.calls(), [['boot', { pluginKey: 'pk-abc123' }]]);
});

test('키가 없으면 채널톡 스크립트를 내려받지 않는다', async () => {
  const chat = await loadChat(undefined);

  assert.deepEqual(chat.appended, []);
  assert.equal(globalThis.window.ChannelIO, undefined);
});

test('키가 있으면 그 키로 부팅한다', async () => {
  const chat = await loadChat('pk-abc123');

  assert.equal(chat.appended.length, 1);
  assert.equal(chat.appended[0].src, 'https://cdn.channel.io/plugin/ch-plugin-web.js');
  assert.deepEqual(chat.calls(), [['boot', { pluginKey: 'pk-abc123' }]]);
});

test('키가 없을 때 문의 버튼은 콘솔 에러 없이 아무 일도 하지 않는다', async () => {
  const chat = await loadChat(undefined);

  const log = capture(() => chat.openChat('상담 문의'));

  assert.deepEqual(log.error, [], '콘솔 에러가 나면 안 된다');
  assert.deepEqual(log.warn, [], '콘솔 경고가 나면 안 된다');
  assert.equal(log.info.length, 1, '왜 안 떴는지는 남긴다');
  assert.deepEqual(chat.appended, []);
});

test('누른 자리를 입력창에 미리 채운 새 상담을 연다', async () => {
  const chat = await loadChat('pk-abc123');

  chat.openChat('정오표 제보');

  // setPage 는 상담이 생길 때 붙는 페이지 값이고, 입력창을 채우는 건 openChat 이다.
  // 둘은 하는 일이 다르므로 둘 다 부른다. chatId 를 비우면 새 상담이 열린다.
  assert.deepEqual(chat.calls().slice(1), [
    ['setPage', '/랜딩#정오표 제보'],
    ['openChat', undefined, '정오표 제보'],
  ]);
});

test('누른 자리를 모르면 메신저만 연다', async () => {
  const chat = await loadChat('pk-abc123');

  chat.openChat();

  // 채울 말이 없는데 새 상담을 강제로 열면 진행 중이던 상담이 갈린다.
  assert.deepEqual(chat.calls().slice(1), [['showMessenger']]);
});

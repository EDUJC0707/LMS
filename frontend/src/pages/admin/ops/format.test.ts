/**
 * 확정 안 된 주차 — 무엇이 목록에 드는가(FLOW 5-1 · 1-4).
 *
 * 경계가 이 목록의 전부다. 날짜가 아무것도 발동시키지 않으므로 앞 주차는
 * 빼먹은 것이 아니고, 오늘 회차는 수업이 끝나야 누른다.
 *
 * 실행: npm test (node:test — TypeScript 를 그대로 읽는다)
 */
import assert from "node:assert/strict";
import { test } from "node:test";

import { unconfirmedSessions } from "./format.ts";

test("지나간 회차 중 안 누른 것만 든다", () => {
  const rows = [
    { session_id: 1, session_date: "2026-08-05", confirmed_at: null }, // 빼먹었다
    { session_id: 2, session_date: "2026-08-12", confirmed_at: "2026-08-12T22:00:00+09:00" },
    { session_id: 3, session_date: "2026-08-19", confirmed_at: null }, // 오늘 — 수업이 안 끝났다
    { session_id: 4, session_date: "2026-08-26", confirmed_at: null }, // 앞일
  ];
  assert.deepEqual(
    unconfirmedSessions(rows, "2026-08-19").map((s) => s.session_id),
    [1],
  );
});

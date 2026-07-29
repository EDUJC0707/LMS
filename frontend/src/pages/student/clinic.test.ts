/**
 * 클리닉 시간 열 — 고른 날짜에 무엇을 그릴지.
 *
 * 전날 마감(2026-07-29 확정)으로 `availability.days` 에서 **오늘이 항상 빠진다**.
 * 그런데 오늘로 잡힌 예약에서 [시간 변경]을 누르면 화면은 그 예약의 날짜를
 * 고른다 — 고른 날짜가 응답 밖인 상태가 생긴다. 그때 날짜만 쓰고 아래를 비워
 * 두면 화면이 아무 말도 하지 않은 채 멈춘다.
 *
 * 실행: npm test (node:test — 별도 러너 설치 없이 TypeScript 를 그대로 읽는다)
 */
import assert from "node:assert/strict";
import { test } from "node:test";

import { timeColumn } from "./lib.ts";
import type { AvailabilityDay } from "./lib.ts";

const WED: AvailabilityDay = {
  date: "2026-07-30",
  weekday: 4,
  times: [
    { slot_id: 231, start_time: "18:00", end_time: "19:00", available: true, reason: null },
    { slot_id: 232, start_time: "19:00", end_time: "20:00", available: false, reason: "마감" },
  ],
};

test("고를 날짜가 아예 없으면 그릴 날짜도 없다", () => {
  assert.deepEqual(timeColumn([], null), { kind: "no-date" });
  assert.deepEqual(timeColumn([WED], null), { kind: "no-date" });
});

test("고른 날짜의 시간 목록을 그대로 넘긴다", () => {
  assert.deepEqual(timeColumn([WED], "2026-07-30"), {
    kind: "open",
    date: "2026-07-30",
    times: WED.times,
  });
});

test("고른 날짜가 응답에 없으면(전날 마감으로 빠진 오늘) 닫혔다고 말한다", () => {
  assert.deepEqual(timeColumn([WED], "2026-07-29"), { kind: "closed", date: "2026-07-29" });
});

test("날짜는 있는데 시간이 하나도 없어도 닫힘이다", () => {
  const empty: AvailabilityDay = { date: "2026-07-31", weekday: 5, times: [] };
  assert.deepEqual(timeColumn([empty], "2026-07-31"), { kind: "closed", date: "2026-07-31" });
});

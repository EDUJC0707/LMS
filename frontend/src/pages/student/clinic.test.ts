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

import { calendarMonths, timeColumn, windowClosed } from "./lib.ts";
import type { AvailabilityDay, ClinicAvailability } from "./lib.ts";

const WED: AvailabilityDay = {
  date: "2026-07-30",
  weekday: 4,
  times: [
    { slot_id: 231, start_time: "18:00", end_time: "19:00", available: true, remaining: 1, reason: null },
    { slot_id: 232, start_time: "19:00", end_time: "20:00", available: false, remaining: 0, reason: "마감" },
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

/* ── 신청 창구(2026-07-29 확정) ─────────────────────────────────────────
   창구는 [내일, 시험 주 다음 월요일]이라 길어야 7일이다. 달력이 그보다 넓게
   움직이면 학생은 고를 게 없는 달을 넘기게 된다. */

function day(date: string, weekday: number): AvailabilityDay {
  return {
    date,
    weekday,
    times: [
      { slot_id: 1, start_time: "18:00", end_time: "19:00", available: true, remaining: 1, reason: null },
    ],
  };
}

function avail(from: string, to: string, days: AvailabilityDay[]): ClinicAvailability {
  return { exam_id: 54, range: { from, to }, days };
}

test("창구가 지난 것은 뒤집힌 구간으로 온다", () => {
  // 시험 7/25(토) → 창구 끝 7/27(월). 7/30 에 조회하면 시작(내일)이 끝보다 뒤다.
  assert.equal(windowClosed({ from: "2026-07-31", to: "2026-07-27" }), true);
  assert.equal(windowClosed({ from: "2026-07-31", to: "2026-08-03" }), false);
  // 하루짜리 창구는 닫힌 것이 아니다.
  assert.equal(windowClosed({ from: "2026-08-03", to: "2026-08-03" }), false);
});

test("달력은 고를 게 있는 첫 달에 서고, 창구가 걸친 달까지만 넘어간다", () => {
  // 시험 7/30(목) → 창구 7/31~8/3. 슬롯이 월~금이라 열린 날은 7/31·8/3.
  const data = avail("2026-07-31", "2026-08-03", [day("2026-07-31", 5), day("2026-08-03", 1)]);
  assert.deepEqual(calendarMonths(data, null), {
    month: "2026-07",
    first: "2026-07",
    last: "2026-08",
  });
});

test("창구가 다음 달에만 걸리면 이번 달을 열지 않는다", () => {
  // 시험 7/31(금) → 창구 8/1~8/3. 8/1(토)·8/2(일)에는 슬롯이 없다.
  const data = avail("2026-08-01", "2026-08-03", [day("2026-08-03", 1)]);
  assert.deepEqual(calendarMonths(data, null), {
    month: "2026-08",
    first: "2026-08",
    last: "2026-08",
  });
});

test("창구 밖 달로는 넘어가지 않는다", () => {
  const data = avail("2026-07-31", "2026-08-03", [day("2026-07-31", 5), day("2026-08-03", 1)]);
  assert.equal(calendarMonths(data, "2026-09").month, "2026-08");
  assert.equal(calendarMonths(data, "2026-06").month, "2026-07");
  assert.equal(calendarMonths(data, "2026-08").month, "2026-08");
});

test("창구가 지났으면 달력은 한 달에 갇힌다", () => {
  const data = avail("2026-07-31", "2026-07-27", []);
  assert.deepEqual(calendarMonths(data, null), {
    month: "2026-07",
    first: "2026-07",
    last: "2026-07",
  });
});

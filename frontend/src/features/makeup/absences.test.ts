/**
 * 동보 신청 대상 판정 — 학생 캘린더 days[] · 학부모 absences[] 공통 규칙.
 *
 * 실행: npm test (node:test — 별도 러너 설치 없이 TypeScript 를 그대로 읽는다)
 */
import assert from "node:assert/strict";
import { test } from "node:test";

import { absencesFromDays, isRequestable, requestableCount } from "./absences.ts";

test("결석한 날만 동보 대상이 된다", () => {
  const rows = absencesFromDays([
    { date: "2026-07-01", attendance: "출석", attendance_id: 211, makeup_status: null },
    { date: "2026-07-04", attendance: "결석", attendance_id: 243, makeup_status: null },
    { date: "2026-07-25", attendance: null, attendance_id: null, makeup_status: null },
  ]);

  assert.deepEqual(rows, [{ date: "2026-07-04", attendance_id: 243, makeup_status: null }]);
});

test("현장 보강으로 끝난 결석은 동보 대상이 아니다", () => {
  // 서버도 absences[] 에서 뺀다(backend curriculum/home.py _MAKEUP_TRACK_STATUSES)
  // — 띄워 두면 신청 버튼을 눌러 400 을 맞는다.
  const rows = absencesFromDays([
    { date: "2026-07-08", attendance: "결석(현보)", attendance_id: 271, makeup_status: null },
  ]);

  assert.deepEqual(rows, []);
});

test("이미 동보로 찍힌 결석은 남기되 신청 버튼은 닫는다", () => {
  const rows = absencesFromDays([
    {
      date: "2026-07-11",
      attendance: "결석(동보)",
      attendance_id: 281,
      makeup_status: "지급완료",
    },
  ]);

  assert.deepEqual(rows, [
    { date: "2026-07-11", attendance_id: 281, makeup_status: "지급완료" },
  ]);
  assert.equal(isRequestable(rows[0]), false);
});

test("출결 번호가 없는 결석은 신청할 수 없으므로 목록에서 뺀다", () => {
  const rows = absencesFromDays([
    { date: "2026-07-04", attendance: "결석", attendance_id: null, makeup_status: null },
  ]);

  assert.deepEqual(rows, []);
});

test("이미 진행 중인 신청은 상태를 그대로 실어 준다", () => {
  const rows = absencesFromDays([
    { date: "2026-07-01", attendance: "결석", attendance_id: 223, makeup_status: "지급완료" },
    { date: "2026-07-15", attendance: "결석", attendance_id: 343, makeup_status: "신청" },
  ]);

  assert.deepEqual(rows, [
    { date: "2026-07-01", attendance_id: 223, makeup_status: "지급완료" },
    { date: "2026-07-15", attendance_id: 343, makeup_status: "신청" },
  ]);
});

test("미신청(null)이면 신청 버튼을 그린다", () => {
  assert.equal(isRequestable({ attendance_id: 243, makeup_status: null }), true);
});

test("신청·승인·지급완료는 살아있는 신청이라 버튼을 숨긴다", () => {
  for (const status of ["신청", "승인", "지급완료"]) {
    assert.equal(
      isRequestable({ attendance_id: 243, makeup_status: status }),
      false,
      `${status} 상태에서 버튼이 뜨면 안 된다`,
    );
  }
});

test("거절된 신청은 다시 신청할 수 있다(서버가 거절만 재신청을 허용한다)", () => {
  assert.equal(isRequestable({ attendance_id: 243, makeup_status: "거절" }), true);
});

test("신청할 수 있는 결석 수를 센다", () => {
  const count = requestableCount([
    { date: "2026-07-01", attendance_id: 223, makeup_status: "지급완료" },
    { date: "2026-07-15", attendance_id: 343, makeup_status: null },
    { date: "2026-07-22", attendance_id: 403, makeup_status: "거절" },
  ]);

  assert.equal(count, 2);
});

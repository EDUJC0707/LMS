/**
 * 출결 값집합의 화면 어휘 — 값이 늘거나 바뀌면 여기서 먼저 걸린다.
 *
 * 실행: npm test (node:test)
 */
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  ATTENDANCE_STATUSES,
  attendanceTone,
  shortAttendance,
} from "./attendance.ts";

test("값집합은 출석 + 결석 3종이다 — 지각은 없다", () => {
  assert.deepEqual(ATTENDANCE_STATUSES, ["출석", "결석", "결석(동보)", "결석(현보)"]);
  assert.equal(ATTENDANCE_STATUSES.includes("지각" as never), false);
});

test("모든 값에 짧은 이름과 색 토큰이 있다", () => {
  // 빠뜨리면 캘린더가 `st-cal__mark--undefined` 를 그린다(색 없는 칸).
  for (const status of ATTENDANCE_STATUSES) {
    assert.ok(shortAttendance(status).length > 0, status);
    assert.ok(attendanceTone(status).length > 0, status);
  }
});

test("짧은 이름은 좁은 칸(캘린더·라디오)에 들어가도록 괄호를 뗀다", () => {
  assert.equal(shortAttendance("결석(동보)"), "동보");
  assert.equal(shortAttendance("결석(현보)"), "현보");
  assert.equal(shortAttendance("출석"), "출석");
});

test("색은 손이 더 가야 하는 것만 danger — 보강이 정해진 결석은 아니다", () => {
  assert.equal(attendanceTone("결석"), "absent");
  assert.notEqual(attendanceTone("결석(동보)"), "absent");
  assert.notEqual(attendanceTone("결석(현보)"), "absent");
});

test("모르는 값도 화면을 깨지 않는다 — 원문을 그대로 쓰고 중립색", () => {
  assert.equal(shortAttendance("휴강"), "휴강");
  assert.equal(attendanceTone("휴강"), "blank");
});

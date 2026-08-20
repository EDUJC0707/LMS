/**
 * `x` 규칙(FLOW 3-1) — 격자에서 유일하게 자명하지 않은 계산이다.
 *
 * 틀리면 조교가 반에 없던 학생의 칸을 영원히 채우려 하거나(x 를 안 그림),
 * 아직 안 본 칸을 "볼 것 없음" 으로 덮는다(x 를 과하게 그림).
 */
import assert from "node:assert/strict";
import { test } from "node:test";

import { cellFor } from "./grid.ts";

test("첫 기록보다 앞선 주차는 x 다", () => {
  const 박지우 = [null, null, "출석", null] as const;
  assert.equal(cellFor([...박지우], 0), "x");
  assert.equal(cellFor([...박지우], 1), "x");
  assert.equal(cellFor([...박지우], 2), "출석");
  // 첫 기록 뒤의 빈 칸은 아직 안 본 것이다 — x 가 아니다
  assert.equal(cellFor([...박지우], 3), "미입력");
});

test("기록이 하나도 없으면 전부 미입력이다", () => {
  assert.equal(cellFor([null, null, null], 0), "미입력");
  assert.equal(cellFor([null, null, null], 2), "미입력");
});

test("명시적 `미입력` 행도 기록이라 그 앞이 x 가 된다", () => {
  assert.equal(cellFor([null, "미입력", "출석"], 0), "x");
  assert.equal(cellFor([null, "미입력", "출석"], 1), "미입력");
});

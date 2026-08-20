/**
 * `x` 규칙(FLOW 3-1) — 격자에서 유일하게 자명하지 않은 계산이다.
 *
 * 틀리면 조교가 반에 없던 학생의 칸을 영원히 채우려 하거나(x 를 안 그림),
 * 아직 안 본 칸을 "볼 것 없음" 으로 덮는다(x 를 과하게 그림).
 */
import assert from "node:assert/strict";
import { test } from "node:test";

import { cellFor, enteredWeeks } from "./grid.ts";

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

test("아직 아무도 안 찍은 주차는 반 전체가 미입력이다", () => {
  // 2주차만 찍고 1주차는 아직 안 찍은 반 — 늦게 온 OMR·건너뛴 주차에서 생긴다.
  const 반 = [{ cells: ["출석", null] as ("출석" | null)[] }, { cells: ["결석", null] as ("결석" | null)[] }];
  const 아직 = enteredWeeks(반 as never, 2);

  assert.deepEqual(아직, [true, false]);
  // 학생만 보면 2주차는 "첫 기록보다 뒤" 라 미입력이고, 여기서도 미입력이어야 한다
  assert.equal(cellFor(반[0].cells as never, 1, 아직[1]), "미입력");
});

test("반 전체가 빈 주차라도 그 뒤에 기록이 있으면 x 가 아니다", () => {
  // 1주차를 아무도 안 찍었고 2주차부터 찍은 반. 1주차가 x 로 찍히면
  // "반에 없었다" 가 되어 미입력(아직 안 봤다)과 뜻이 뒤집힌다.
  const 반 = [{ cells: [null, "출석"] as (string | null)[] }, { cells: [null, "출석"] as (string | null)[] }];
  const 아직 = enteredWeeks(반 as never, 2);

  assert.deepEqual(아직, [false, true]);
  assert.equal(cellFor(반[0].cells as never, 0, 아직[0]), "미입력");
});

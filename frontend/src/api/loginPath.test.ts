/**
 * 로그인 경로 선택 — 백엔드 2026-07-28 개편.
 * 소비자(학생·학부모)는 한 경로를 공유하고, 직원만 별도 경로다.
 *
 * 실행: npm test
 */
import assert from "node:assert/strict";
import { test } from "node:test";

import { LOGIN_PATH, loginPathFor } from "./loginPath.ts";

test("학생과 학부모는 같은 로그인 경로를 쓴다", () => {
  assert.equal(loginPathFor("consumer"), "/auth/login");
});

test("직원 로그인만 별도 경로다", () => {
  assert.equal(loginPathFor("admin"), "/auth/login/admin");
});

test("삭제된 역할별 경로(student·parent)는 더 이상 존재하지 않는다", () => {
  assert.deepEqual(Object.keys(LOGIN_PATH).sort(), ["admin", "consumer"]);
});

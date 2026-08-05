/**
 * 학생 명부 조회 파라미터 조립 — GET /api/admin/students.
 *
 * 서버가 400 을 주는 조합(값집합 밖 enrollment_status·비정수 course_id)을
 * 애초에 만들지 않는 것이 이 모듈의 일이다.
 */
import assert from "node:assert/strict";
import { test } from "node:test";

import { directoryParams, mergePreRegistered } from "./directory.ts";

test("검색어가 비어 있으면 q 를 아예 보내지 않는다", () => {
  assert.deepEqual(directoryParams({ q: "" }), {});
  assert.deepEqual(directoryParams({ q: "   " }), {});
});

test("검색어는 앞뒤 공백을 떼고 보낸다", () => {
  assert.deepEqual(directoryParams({ q: "  하늘 " }), { q: "하늘" });
});

test("등록 상태는 값집합에 있을 때만 보낸다", () => {
  assert.deepEqual(directoryParams({ enrollment_status: "예비등록" }), {
    enrollment_status: "예비등록",
  });
  assert.deepEqual(directoryParams({ enrollment_status: "" }), {});
  assert.deepEqual(directoryParams({ enrollment_status: "휴원" }), {});
});

test("첫 페이지는 page 를 붙이지 않는다", () => {
  assert.deepEqual(directoryParams({ page: 1 }), {});
  assert.deepEqual(directoryParams({ page: 2 }), { page: 2 });
});

test("조건은 겹쳐서 보낼 수 있다", () => {
  assert.deepEqual(directoryParams({ q: "김하늘0001", enrollment_status: "등록", page: 3 }), {
    q: "김하늘0001",
    enrollment_status: "등록",
    page: 3,
  });
});

test("예비등록 명부에 출석부의 출결을 붙인다", () => {
  const merged = mergePreRegistered(
    [
      {
        student_id: 59,
        name: "장예준",
        login_id: "장예준0029",
        matching_key: "장예준0029",
        grade: "고2",
        current_class: "수요반",
        enrollment_status: "예비등록",
      },
      {
        student_id: 60,
        name: "임다인",
        login_id: "임다인0030",
        matching_key: "임다인0030",
        grade: "고2",
        current_class: "토요반",
        enrollment_status: "예비등록",
      },
    ],
    [
      {
        student_id: 59,
        name: "장예준",
        login_id: "장예준0029",
        matching_key: "장예준0029",
        current_class: "수요반",
        enrollment_status: "예비등록",
        attendance: { status: "출석", exam_taken: false, marked_at: null, updated_at: null },
      },
    ],
  );

  assert.equal(merged.length, 2);
  assert.equal(merged[0].attendance_status, "출석");
  assert.equal(merged[1].attendance_status, null);
});

test("출석부를 못 읽으면 명부만으로 목록을 만든다", () => {
  const merged = mergePreRegistered(
    [
      {
        student_id: 59,
        name: null,
        login_id: null,
        matching_key: "",
        grade: "",
        current_class: null,
        enrollment_status: "예비등록",
      },
    ],
    null,
  );

  assert.deepEqual(merged, [
    {
      student_id: 59,
      name: null,
      login_id: null,
      matching_key: "",
      grade: "",
      current_class: null,
      enrollment_status: "예비등록",
      attendance_status: null,
    },
  ]);
});

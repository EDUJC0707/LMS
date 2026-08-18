/**
 * 붙여넣은 명단의 열 지정 — 고정 순서로 자르던 시절의 조용한 오류를 막는다.
 *
 * 학원 파일 순서(이름·학교·학년·학생폰·학부모폰)를 옛 순서로 자르면 학교명이
 * 폰 칸에 들어가고 학년 칸의 번호로 아이디가 만들어진다. 되돌릴 수 없는 값이라
 * "틀리면 안 된다"가 아니라 "틀릴 수 없어야" 한다.
 */
import assert from "node:assert/strict";
import { test } from "node:test";

import { assignColumn, isMapped, readPasted, toEntries } from "./paste.ts";

const ACADEMY = ["이름\t학교\t학년\t학생 연락처\t학부모 연락처", "김하늘\t세화고\t고2\t01011112222\t01033334444"].join(
  "\n",
);

test("학원 파일 머리줄을 읽어 열을 맞춘다", () => {
  const table = readPasted(ACADEMY);
  assert.equal(table.headerRow, true);
  assert.deepEqual(table.mapping, ["name", "school", "grade", "phone", "parent_phone"]);
  assert.deepEqual(toEntries(table), [
    {
      name: "김하늘",
      phone: "01011112222",
      parent_phone: "01033334444",
      grade: "고2",
      school: "세화고",
    },
  ]);
});

test("머리줄이 없으면 아무 열도 맞히지 않는다", () => {
  const table = readPasted("김하늘\t세화고\t고2\t01011112222\t01033334444");
  assert.equal(table.headerRow, false);
  assert.deepEqual(table.mapping, ["", "", "", "", ""]);
  assert.equal(isMapped(table.mapping), false);
});

test("조교가 고른 열로 값이 들어간다", () => {
  const table = readPasted("김하늘\t세화고\t01011112222");
  let mapping = assignColumn(table.mapping, 0, "name");
  mapping = assignColumn(mapping, 1, "school");
  mapping = assignColumn(mapping, 2, "phone");
  assert.equal(isMapped(mapping), true);
  assert.deepEqual(toEntries({ ...table, mapping }), [
    { name: "김하늘", phone: "01011112222", parent_phone: "", grade: "", school: "세화고" },
  ]);
});

test("한 필드는 한 열에만 붙는다", () => {
  const mapping = assignColumn(["phone", "", ""], 2, "phone");
  assert.deepEqual(mapping, ["", "", "phone"]);
});

test("지정하지 않은 열은 버린다", () => {
  const table = readPasted("이름\t비고\t학생 연락처\n김하늘\t재수강\t01011112222");
  assert.deepEqual(table.mapping, ["name", "", "phone"]);
  assert.deepEqual(toEntries(table), [
    { name: "김하늘", phone: "01011112222", parent_phone: "", grade: "", school: "" },
  ]);
});

test("쉼표로 온 파일도 같은 격자가 된다", () => {
  const table = readPasted("이름,학생 연락처\n김하늘,01011112222");
  assert.deepEqual(table.mapping, ["name", "phone"]);
  assert.equal(toEntries(table).length, 1);
});

test("빈 줄과 값이 하나도 없는 줄은 버린다", () => {
  const table = readPasted("이름\t학생 연락처\n\n김하늘\t01011112222\n\t");
  assert.equal(toEntries(table).length, 1);
});

test("아는 이름이 하나뿐이면 머리줄로 보지 않는다", () => {
  // 값 한 줄을 머리줄로 오해하면 그 학생이 통째로 사라진다.
  const table = readPasted("김하늘\t01011112222\n이서준\t01022223333");
  assert.equal(table.headerRow, false);
  assert.equal(toEntries({ ...table, mapping: ["name", "phone"] }).length, 2);
});

test("같은 뜻의 머리줄이 두 번 오면 앞 열만 맞춘다", () => {
  const table = readPasted("이름\t성명\t학년\n김하늘\t김하늘\t고2");
  assert.deepEqual(table.mapping, ["name", "", "grade"]);
});

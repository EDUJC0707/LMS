/**
 * 붙여넣은 명단의 열 지정 — 고정 순서로 자르던 시절의 조용한 오류를 막는다.
 *
 * 학원 파일 순서(이름·학교·학년·학생폰·학부모폰)를 옛 순서로 자르면 학교명이
 * 폰 칸에 들어가고 학년 칸의 번호로 아이디가 만들어진다. 되돌릴 수 없는 값이라
 * "틀리면 안 된다"가 아니라 "틀릴 수 없어야" 한다.
 */
import assert from "node:assert/strict";
import { test } from "node:test";

import type { AliasMap } from "./paste.ts";
import { assignColumn, guessField, isMapped, newAliases, readPasted, toEntries } from "./paste.ts";

/** 서버 별칭표 자리 — 이 모듈은 표를 받아 맞춰만 보고 갖고 있지 않다. */
const ALIASES: AliasMap = {
  이름: "name",
  성명: "name",
  학교: "school",
  학년: "grade",
  학생연락처: "phone",
  학부모연락처: "parent_phone",
};

const ACADEMY = ["이름\t학교\t학년\t학생 연락처\t학부모 연락처", "김하늘\t세화고\t고2\t01011112222\t01033334444"].join(
  "\n",
);

test("학원 파일 머리줄을 읽어 열을 맞춘다", () => {
  const table = readPasted(ACADEMY, ALIASES);
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
  const table = readPasted("김하늘\t세화고\t고2\t01011112222\t01033334444", ALIASES);
  assert.equal(table.headerRow, false);
  assert.deepEqual(table.mapping, ["", "", "", "", ""]);
  assert.equal(isMapped(table.mapping), false);
});

test("조교가 고른 열로 값이 들어간다", () => {
  const table = readPasted("김하늘\t세화고\t01011112222", ALIASES);
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
  const table = readPasted("이름\t비고\t학생 연락처\n김하늘\t재수강\t01011112222", ALIASES);
  assert.deepEqual(table.mapping, ["name", "", "phone"]);
  assert.deepEqual(toEntries(table), [
    { name: "김하늘", phone: "01011112222", parent_phone: "", grade: "", school: "" },
  ]);
});

test("쉼표로 온 파일도 같은 격자가 된다", () => {
  const table = readPasted("이름,학생 연락처\n김하늘,01011112222", ALIASES);
  assert.deepEqual(table.mapping, ["name", "phone"]);
  assert.equal(toEntries(table).length, 1);
});

test("빈 줄과 값이 하나도 없는 줄은 버린다", () => {
  const table = readPasted("이름\t학생 연락처\n\n김하늘\t01011112222\n\t", ALIASES);
  assert.equal(toEntries(table).length, 1);
});

test("아는 이름이 하나뿐이면 머리줄로 보지 않는다", () => {
  // 값 한 줄을 머리줄로 오해하면 그 학생이 통째로 사라진다.
  const table = readPasted("김하늘\t01011112222\n이서준\t01022223333", ALIASES);
  assert.equal(table.headerRow, false);
  assert.equal(toEntries({ ...table, mapping: ["name", "phone"] }).length, 2);
});

test("같은 뜻의 머리줄이 두 번 오면 앞 열만 맞춘다", () => {
  const table = readPasted("이름\t성명\t학년\n김하늘\t김하늘\t고2", ALIASES);
  assert.deepEqual(table.mapping, ["name", "", "grade"]);
});

test("조교가 새로 답한 머리줄만 별칭표로 올라간다", () => {
  // `학생 HP` 는 표에 없다 — 조교가 골라 준 것이라 남겨야 다음번에 안 묻는다.
  // `이름` 은 이미 표에 있으므로 다시 넣지 않는다.
  const table = readPasted("이름\t학생 HP\t학년\n김하늘\t01011112222\t고2", ALIASES);
  const mapping = assignColumn(table.mapping, 1, "phone");
  assert.deepEqual(newAliases({ ...table, mapping }, ALIASES), [
    { alias: "학생 HP", target: "phone" },
  ]);
});

test("머리줄이 아니면 남길 별칭이 없다", () => {
  const table = readPasted("김하늘\t01011112222", ALIASES);
  assert.deepEqual(newAliases({ ...table, mapping: ["name", "phone"] }, ALIASES), []);
});

test("맥에서 만든 머리줄(NFD)도 별칭표에 맞는다", () => {
  // 별칭표는 NFC 로 저장된다(서버 `alias_key`). 맥 파일은 자모가 분해돼 오므로
  // 정규화를 빠뜨리면 눈으로 같은 글자가 대조에서 빗나가 열이 전부 수동으로 떨어진다.
  const aliases: AliasMap = { 학생연락처: "phone" };

  assert.equal(guessField("학생 연락처".normalize("NFD"), aliases), "phone");
  assert.equal(guessField("학생 연락처".normalize("NFC"), aliases), "phone");
});

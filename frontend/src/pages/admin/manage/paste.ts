/**
 * 붙여넣은 명단 → 발급 행. **열 순서를 우리가 정하지 않는다**(FLOW 2-1·2-2).
 *
 * 파일은 학원이 주는 것이고 같은 뜻인데 매번 다르게 온다. 예전에는 고정 순서
 * (이름·학생폰·학부모폰·학년·학교)로 잘랐는데, 학원 파일은 이름·학교·학년·
 * 학생폰·학부모폰 순으로 온다 — 그대로 붙이면 **학교명이 폰 칸에 들어가고
 * 학년 칸의 번호로 아이디 뒷4자리가 만들어진다.** 조용히 틀리고, 아이디와
 * 대조키는 이후 안 바뀌는 값이라 되돌릴 수 없다.
 *
 * 그래서 자르는 것과 **어느 열이 무엇인지**를 나눈다. 머리줄이 있으면 아는
 * 이름은 맞춰 두고(FLOW 2-2 ②), 모르면 비워 둔 채 조교가 고른다(③).
 *
 * **별칭표는 아직 없다**(FLOW 2-2 는 저장을 말한다). 같은 학원 파일은 머리줄도
 * 같아서 다음번에도 자동으로 맞고, 안 맞는 것만 사람이 고른다 — 표를 만들어
 * 저장하는 것은 그 다음 문제다.
 */

/** 발급 행이 받는 값 — AccountsPage 의 EntryRow 와 같은 축. */
export type EntryField = "name" | "phone" | "parent_phone" | "grade" | "school";

/** 열에 붙는 것: 필드 하나 또는 "쓰지 않음"(빈 문자열). */
export type ColumnChoice = EntryField | "";

export interface PastedTable {
  /** 붙여넣은 그대로 — 자르기만 했다. */
  cells: string[][];
  /** 열마다 무엇인지. cells 의 열 수와 길이가 같다. */
  mapping: ColumnChoice[];
  /** 첫 줄이 머리줄이면 값으로 읽지 않는다. */
  headerRow: boolean;
}

/**
 * 머리줄에서 아는 이름들. 공백·구두점을 뗀 소문자로 비교한다.
 * 여기 없는 이름은 조교가 고르는 쪽으로 넘어간다 — 억지로 맞히지 않는다.
 */
const ALIASES: Record<EntryField, string[]> = {
  name: ["이름", "성명", "학생이름", "학생성명", "학생명", "name"],
  phone: [
    "학생휴대폰",
    "학생휴대전화",
    "학생핸드폰",
    "학생폰",
    "학생전화",
    "학생전화번호",
    "학생연락처",
    "학생번호",
    "학생hp",
    "휴대폰",
    "휴대전화",
    "핸드폰",
    "전화",
    "전화번호",
    "연락처",
  ],
  parent_phone: [
    "학부모휴대폰",
    "학부모휴대전화",
    "학부모핸드폰",
    "학부모폰",
    "학부모전화",
    "학부모전화번호",
    "학부모연락처",
    "학부모번호",
    "학부모hp",
    "학부모",
    "보호자휴대폰",
    "보호자핸드폰",
    "보호자폰",
    "보호자전화",
    "보호자연락처",
    "보호자",
    "부모님연락처",
    "모연락처",
    "부연락처",
  ],
  grade: ["학년", "재학학년"],
  school: ["학교", "학교명", "출신학교", "재학학교", "고교"],
};

const FIELDS = Object.keys(ALIASES) as EntryField[];

const squash = (cell: string) => cell.replace(/[\s.·_/()-]/g, "").toLowerCase();

/** 머리줄 한 칸 → 필드. 모르면 "". */
export function guessField(cell: string): ColumnChoice {
  const key = squash(cell);
  if (!key) return "";
  return FIELDS.find((field) => ALIASES[field].includes(key)) ?? "";
}

/** 엑셀·메모장에서 복사한 덩어리를 격자로 자른다(탭·쉼표 모두 허용). */
export function splitPasted(text: string): string[][] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
    .map((line) => line.split(/\t|,/).map((cell) => cell.trim()));
}

/**
 * 붙여넣은 표를 읽는다 — 자르고, 아는 머리줄이면 열을 맞춰 둔다.
 *
 * 머리줄로 보는 조건은 **아는 이름이 둘 이상**이다. 하나만 맞는 줄은 값일 수
 * 있어서(학교 이름이 "학년"인 경우는 없지만 이름이 "연락처"인 학생도 없다),
 * 사람 줄 하나를 통째로 날리는 쪽보다 안 맞히는 쪽이 낫다.
 */
export function readPasted(text: string): PastedTable {
  const cells = splitPasted(text);
  const width = cells.reduce((max, row) => Math.max(max, row.length), 0);
  const blank: ColumnChoice[] = Array.from({ length: width }, () => "");
  if (cells.length === 0) return { cells, mapping: blank, headerRow: false };

  const guessed = blank.map((_, index) => guessField(cells[0][index] ?? ""));
  const known = guessed.filter((choice) => choice !== "").length;
  if (known < 2) return { cells, mapping: blank, headerRow: false };
  // 같은 필드가 두 열에 걸리면 앞 열만 남긴다 — 뒤 열은 조교가 고른다.
  const seen = new Set<ColumnChoice>();
  const mapping = guessed.map((choice) => {
    if (choice === "" || seen.has(choice)) return "";
    seen.add(choice);
    return choice;
  });
  return { cells, mapping, headerRow: true };
}

/** 한 열에 필드를 건다 — 그 필드를 쓰던 다른 열은 비운다(한 필드는 한 열). */
export function assignColumn(
  mapping: ColumnChoice[],
  index: number,
  choice: ColumnChoice,
): ColumnChoice[] {
  return mapping.map((current, i) => {
    if (i === index) return choice;
    return choice !== "" && current === choice ? "" : current;
  });
}

/** 이름 열이 없으면 발급할 수 없다 — 서버가 행마다 실패시킨다. */
export function isMapped(mapping: ColumnChoice[]): boolean {
  return mapping.includes("name");
}

/** 지정한 열만 뽑아 발급 행으로 만든다. 값이 하나도 없는 줄은 버린다. */
export function toEntries(table: PastedTable): Record<EntryField, string>[] {
  const body = table.headerRow ? table.cells.slice(1) : table.cells;
  return body
    .map((row) => {
      const entry: Record<EntryField, string> = {
        name: "",
        phone: "",
        parent_phone: "",
        grade: "",
        school: "",
      };
      table.mapping.forEach((choice, index) => {
        if (choice) entry[choice] = row[index] ?? "";
      });
      return entry;
    })
    .filter((entry) => FIELDS.some((field) => entry[field] !== ""));
}

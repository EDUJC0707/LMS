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
 * **아는 이름은 별칭표에서 온다**(FLOW 2-2). 표는 서버에 있고 전역이라 어느
 * 학원 파일이든 같은 표를 본다 — 이 모듈은 표를 받아 맞춰만 보고, 조교가 새로
 * 답한 것은 화면이 발급 성공 뒤에 표에 넣는다(`newAliases`).
 */

/** 발급 행이 받는 값 — AccountsPage 의 EntryRow 와 같은 축. */
export type EntryField = "name" | "phone" | "parent_phone" | "grade" | "school";

/** 열에 붙는 것: 필드 하나 또는 "쓰지 않음"(빈 문자열). */
export type ColumnChoice = EntryField | "";

/**
 * 열 이름 — 발급 화면의 열 지정과 별칭표 화면이 **같은 문자열**을 쓴다.
 * 별칭표에 붙일 열을 고르는 자리와 붙여넣은 표의 열을 고르는 자리가 다른
 * 이름을 쓰면, 조교가 저장한 답과 화면에 보이는 답이 달라 보인다.
 */
export const FIELD_LABELS: Record<EntryField, string> = {
  name: "이름",
  phone: "학생 휴대폰",
  parent_phone: "학부모 휴대폰",
  grade: "학년",
  school: "학교",
};

export interface PastedTable {
  /** 붙여넣은 그대로 — 자르기만 했다. */
  cells: string[][];
  /** 열마다 무엇인지. cells 의 열 수와 길이가 같다. */
  mapping: ColumnChoice[];
  /** 첫 줄이 머리줄이면 값으로 읽지 않는다. */
  headerRow: boolean;
}

/** 별칭표 — `squash` 한 머리줄 → 열. 서버 `GET /api/admin/aliases` 가 준다. */
export type AliasMap = Record<string, EntryField>;


const FIELDS = Object.keys(FIELD_LABELS) as EntryField[];

/**
 * 별칭 대조 키. **`backend/apps/accounts/aliases.py` 의 `alias_key()` 와 글자까지
 * 같은 값**을 내야 한다 — 여기서 맞춰 보고 저쪽이 저장·조회하므로, 두 규칙이
 * 갈리면 조교가 방금 답한 별칭이 다음 파일에서 안 맞는다.
 */
const squash = (cell: string) => cell.replace(/[\s.·_/()-]/g, "").toLowerCase();

/** 머리줄 한 칸 → 필드. 표에 없으면 "". */
export function guessField(cell: string, aliases: AliasMap): ColumnChoice {
  return aliases[squash(cell)] ?? "";
}

/**
 * 이 표에서 **조교가 새로 답한** 머리줄 — 표에 이미 있는 것은 뺀다.
 *
 * 저장은 화면이 발급에 성공한 뒤에 한다(FLOW 5-1). 표가 전역이라 잘못 붙은
 * 별칭 하나가 이후 모든 명단을 조용히 물들이므로, 고르는 도중에는 남기지
 * 않는다.
 */
export function newAliases(
  table: PastedTable,
  aliases: AliasMap,
): { alias: string; target: EntryField }[] {
  if (!table.headerRow) return [];
  return table.mapping.flatMap((choice, index) => {
    const header = table.cells[0]?.[index] ?? "";
    if (!choice || !squash(header) || guessField(header, aliases)) return [];
    return [{ alias: header, target: choice }];
  });
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
export function readPasted(text: string, aliases: AliasMap): PastedTable {
  const cells = splitPasted(text);
  const width = cells.reduce((max, row) => Math.max(max, row.length), 0);
  const blank: ColumnChoice[] = Array.from({ length: width }, () => "");
  if (cells.length === 0) return { cells, mapping: blank, headerRow: false };

  const guessed = blank.map((_, index) => guessField(cells[0][index] ?? "", aliases));
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

/**
 * 반별 격자의 칸 하나 — `x` 를 그리는 자리 (FLOW 3-1).
 *
 * **`x` 는 저장하지 않는다.** 값집합에도 없고 서버도 보내지 않는다. 그 학생의
 * **첫 기록보다 앞선 주차**면 여기서 그린다 — 합류 주차를 따로 담을 필요가 없다.
 *
 * `미입력`(3-4)과 갈라 놓는 것이 요점이다. 미입력은 "아직 안 봤다" 이고 `x` 는
 * "볼 것이 없다" 다. 3주차에 들어온 학생의 1·2주차를 미입력으로 두면 조교가
 * 영원히 채워야 할 칸으로 남는다.
 *
 * 기록이 하나도 없는 학생은 앞선 칸이 없으므로 **전부 미입력**이다 — 반에 없던
 * 것이 아니라 아무도 안 본 것이다. 명시적 `미입력` 행도 기록이다(찍은 것을 조교가
 * 해제한 자리라 그 앞은 이미 이 반이었다).
 *
 * **아직 아무도 안 찍은 주차는 통째로 미입력이다**(`entered=false`). 학생 한 명만
 * 보면 그 주차는 "첫 기록보다 앞" 이라 `x` 로 보이는데, 반 전체가 비어 있다면
 * 그건 아무도 안 들어온 주차가 아니라 **아직 안 찍은 주차**다. 늦게 온 OMR 이나
 * 건너뛴 주차에서 실제로 생기고(FLOW 5-1 이 그 화면을 따로 둔다), 그때 반 전원이
 * "볼 것이 없다" 로 찍히면 미입력/`x` 를 가른 이유가 통째로 뒤집힌다.
 */
import type { AttendanceStatus } from "../../../features/attendance";

export type GridCell = AttendanceStatus | "x";

/** 주차마다 "이 반에서 한 명이라도 기록이 있는가" — `cellFor` 의 `entered` 다. */
export function enteredWeeks(rows: { cells: (AttendanceStatus | null)[] }[], weeks: number) {
  return Array.from({ length: weeks }, (_, i) => rows.some((row) => row.cells[i] != null));
}

export function cellFor(
  cells: (AttendanceStatus | null)[],
  index: number,
  entered = true,
): GridCell {
  const value = cells[index];
  if (value != null) return value;
  if (!entered) return "미입력";
  const first = cells.findIndex((cell) => cell != null);
  return first !== -1 && index < first ? "x" : "미입력";
}

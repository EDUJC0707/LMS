/**
 * 동보(결석 보강영상) 신청 대상 판정 — 학생·학부모 공통 규칙.
 *
 * 서버가 두 화면에 같은 필드를 내려준다(2026-07-28 실측):
 *   GET /api/student/home  → calendar.days[]  { date, attendance, attendance_id, makeup_status }
 *   GET /api/parent/home   → absences[]       { date, attendance_id, makeup_status }
 * 두 화면이 같은 판정을 쓰도록 규칙을 여기 한 곳에만 둔다.
 *
 * makeup_status 값집합: null(미신청) · 신청 · 지급완료 · 거절.
 * 서버는 **거절만 재신청을 허용**한다(backend/apps/videos/views.py `_ACTIVE_STATUSES`)
 * — 그래서 거절은 버튼을 다시 띄운다. 신청·지급완료는 살아있는 신청이라 숨긴다.
 */

/** 동보 신청 단위 — 결석 하나. attendance_id 가 그대로 신청 body 의 키다. */
export interface MakeupAbsence {
  attendance_id: number;
  date: string;
  /** null = 아직 신청 전 */
  makeup_status: string | null;
}

/** 캘린더 한 칸. 출결이 없는 예정일은 attendance·attendance_id 가 전부 null 이다. */
export interface CalendarDayLike {
  date: string;
  attendance: string | null;
  attendance_id: number | null;
  makeup_status: string | null;
}

/** 서버가 "살아있는 신청"으로 보는 상태 — 이때는 신청 버튼을 그리지 않는다. */
const ACTIVE_STATUSES = ["신청", "지급완료"];

/**
 * 동보 축에 있는 출결 값 — 서버 `_MAKEUP_TRACK_STATUSES`(curriculum/home.py)와 같다.
 * `결석(현보)` 는 뺀다: 현장 보강이 끝난 결석이라 서버가 동보 신청을 400 으로 막는다.
 * (출결 값집합은 2026-07-29 개편으로 출석/결석/결석(동보)/결석(현보) 4종)
 */
const MAKEUP_TRACK_STATUSES = ["결석", "결석(동보)"];

/**
 * 캘린더 날짜 배열에서 동보 신청 대상(결석)만 뽑는다.
 * 출결 번호가 없는 결석은 신청할 방법이 없으므로 목록에 넣지 않는다.
 */
export function absencesFromDays(days: CalendarDayLike[]): MakeupAbsence[] {
  const rows: MakeupAbsence[] = [];
  for (const day of days) {
    if (day.attendance === null || !MAKEUP_TRACK_STATUSES.includes(day.attendance)) continue;
    if (day.attendance_id === null) continue;
    rows.push({
      date: day.date,
      attendance_id: day.attendance_id,
      makeup_status: day.makeup_status,
    });
  }
  return rows;
}

/** 지금 신청할 수 있는 결석인가 — 버튼을 그릴지 판단하는 유일한 기준. */
export function isRequestable(row: {
  attendance_id: number | null;
  makeup_status: string | null;
}): boolean {
  if (row.attendance_id === null) return false;
  if (row.makeup_status === null) return true;
  return !ACTIVE_STATUSES.includes(row.makeup_status);
}

/** 신청할 수 있는 결석 수 — 0 이면 "신청" 열 자체를 만들지 않는다. */
export function requestableCount(rows: readonly MakeupAbsence[]): number {
  return rows.filter(isRequestable).length;
}

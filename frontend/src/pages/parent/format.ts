/** 학부모 화면 공용 표시 형식 — 날짜·금액·점수를 한국어 문장으로 맞춘다. */

const WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"];

/** "2026-07" 형태의 이번 달. */
export function currentMonth(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

export function shiftMonth(month: string, delta: number): string {
  const [year, monthNo] = month.split("-").map(Number);
  const moved = new Date(year, monthNo - 1 + delta, 1);
  return `${moved.getFullYear()}-${String(moved.getMonth() + 1).padStart(2, "0")}`;
}

export function monthLabel(month: string): string {
  const [year, monthNo] = month.split("-").map(Number);
  return `${year}년 ${monthNo}월`;
}

/** 로컬 기준으로 "2026-07-22" 를 안전하게 쪼갠다(UTC 파싱 어긋남 방지). */
function parts(date: string): [number, number, number] {
  const [year, month, day] = date.split("-").map(Number);
  return [year, month, day];
}

export function weekdayName(index: number): string {
  return WEEKDAYS[index] ?? "";
}

/** "7월 22일 (수)" */
export function dayLabel(date: string): string {
  const [year, month, day] = parts(date);
  const weekday = WEEKDAYS[new Date(year, month - 1, day).getDay()];
  return `${month}월 ${day}일 (${weekday})`;
}

/** "7월 22일" — 표 안처럼 좁은 자리용. */
export function shortDay(date: string): string {
  const [, month, day] = parts(date);
  return `${month}월 ${day}일`;
}

/** ISO 시각 → "7월 22일 21:47" */
export function dateTimeLabel(iso: string): string {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return iso;
  const hour = String(at.getHours()).padStart(2, "0");
  const minute = String(at.getMinutes()).padStart(2, "0");
  return `${at.getMonth() + 1}월 ${at.getDate()}일 ${hour}:${minute}`;
}

export function money(amount: number): string {
  return `${amount.toLocaleString("ko-KR")}원`;
}

/** 소수점이 붙어 내려오는 점수·평균을 사람이 읽는 자리수로. */
export function score(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined) return "—";
  return Number.isInteger(value) ? String(value) : value.toFixed(digits);
}

/**
 * 서버가 준 제목이 이미 번호로 시작하면(예: "1주차 — 역학 심화") 번호를 덧붙이지
 * 않는다. "1주차 · 1주차 — 역학 심화" 같은 겹말을 막는다.
 */
export function withPrefix(prefix: string, title?: string | null): string {
  if (!title) return prefix;
  const squeeze = (text: string) => text.replace(/\s/g, "");
  return squeeze(title).startsWith(squeeze(prefix)) ? title : `${prefix} · ${title}`;
}

/** 마감까지 남은 날 — D-3 · 오늘 · 2일 지남 */
export function dDayLabel(dDay: number | null | undefined): string {
  if (dDay === null || dDay === undefined) return "기한 없음";
  if (dDay === 0) return "오늘";
  if (dDay > 0) return `D-${dDay}`;
  return `${-dDay}일 지남`;
}

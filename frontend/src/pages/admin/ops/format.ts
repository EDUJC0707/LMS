/** 운영 화면 공통 날짜·문장 도우미. 서버는 로컬 날짜 문자열(YYYY-MM-DD)을 준다. */

const WEEKDAY = ["일", "월", "화", "수", "목", "금", "토"];

function parts(iso: string): [number, number, number] {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return [y, m, d];
}

/** 오늘 날짜를 서버와 같은 YYYY-MM-DD 로. (UTC 변환을 거치지 않는다) */
export function todayISO(): string {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

/** "7월 18일(금)" */
export function shortDate(iso: string | null): string {
  if (!iso) return "—";
  const [y, m, d] = parts(iso);
  const day = WEEKDAY[new Date(y, m - 1, d).getDay()];
  return `${m}월 ${d}일(${day})`;
}

/** "2026년 7월 18일(금)" */
export function longDate(iso: string | null): string {
  if (!iso) return "—";
  const [y] = parts(iso);
  return `${y}년 ${shortDate(iso)}`;
}

/** "7월 22일 21:47" — 서버가 준 ISO 타임스탬프용. */
export function stamp(iso: string | null): string {
  if (!iso) return "—";
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return "—";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${at.getMonth() + 1}월 ${at.getDate()}일 ${pad(at.getHours())}:${pad(at.getMinutes())}`;
}

/** 오늘 기준 남은 날 수를 사람 말로. "오늘" · "내일" · "3일 뒤" · "5일 전" */
export function relativeDay(iso: string, today: string): string {
  const [ty, tm, td] = parts(today);
  const [y, m, d] = parts(iso);
  const diff = Math.round(
    (new Date(y, m - 1, d).getTime() - new Date(ty, tm - 1, td).getTime()) / 86_400_000,
  );
  if (diff === 0) return "오늘";
  if (diff === 1) return "내일";
  if (diff === -1) return "어제";
  return diff > 0 ? `${diff}일 뒤` : `${-diff}일 전`;
}

/** "목 6.5 대치러셀 · 로직엔제 3주차 6차시" — 없는 조각은 자연스럽게 빠진다.
 *
 *  **반이 맨 앞이다.** 같은 커리를 목반과 화반이 같이 듣기 때문에(FLOW 1-1)
 *  강좌명과 주차만 그리면 두 반의 3주차가 한 글자도 다르지 않게 뜬다. 반이
 *  없이 만들어진 옛 회차는 종전대로 강좌명부터다.
 */
export function sessionLabel(session: {
  session_no: number | null;
  week_no: number | null;
  course: { name: string } | null;
  klass?: { name: string } | null;
}): string {
  const bits: string[] = [];
  if (session.course) bits.push(session.course.name);
  if (session.week_no !== null) bits.push(`${session.week_no}주차`);
  if (session.session_no !== null) bits.push(`${session.session_no}차시`);
  const rest = bits.join(" ");
  if (session.klass) return rest === "" ? session.klass.name : `${session.klass.name} · ${rest}`;
  return rest === "" ? "커리큘럼 미매핑 회차" : rest;
}

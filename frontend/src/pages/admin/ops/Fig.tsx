import "./ops.css";

/**
 * 집계 수치 한 칸(대시보드 회차 카드 · 출결 입력 고정 바 공용).
 * 상태색은 의미 전용 — 출석/지각/결석/미입력에만 쓴다.
 */
export function Fig({
  tone,
  n,
  label,
}: {
  tone: "present" | "late" | "absent" | "blank";
  n: number;
  label: string;
}) {
  return (
    <span className={`ops-fig ops-fig--${tone}`}>
      <span className={`ops-fig__n num ${n === 0 ? "is-zero" : ""}`.trim()}>{n}</span>
      <span className="ops-fig__l">{label}</span>
    </span>
  );
}

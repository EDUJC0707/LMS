import "./ops.css";

/**
 * 집계 수치 한 칸(대시보드 회차 카드 · 출결 입력 고정 바 공용).
 * 상태색은 의미 전용 — 출결 값 4종과 미입력에만 쓴다(2026-07-29 값집합 개편).
 * 색은 "손이 얼마나 더 가야 하는가" 순이다: 결석(danger)만 전화가 남고,
 * 동보(warning)·현보(accent)는 보강이 이미 정해졌거나 끝났다.
 */
export function Fig({
  tone,
  n,
  label,
}: {
  tone: "present" | "makeup" | "onsite" | "absent" | "blank";
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

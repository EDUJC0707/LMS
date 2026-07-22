import { diffInDays, formatMonthDay, parseISODate } from "./dates";
import type { Deadline } from "./types";

function urgencyOf(dday: number): "now" | "soon" | "later" {
  if (dday <= 0) return "now";
  if (dday <= 2) return "soon";
  return "later";
}

interface DeadlineRailProps {
  deadlines: Deadline[];
  todayISO: string;
}

/* 마감 임박 카드 — 클리닉·영상 만료·결제 기한을 D-n 순으로 우선 노출 */
export default function DeadlineRail({ deadlines, todayISO }: DeadlineRailProps) {
  const today = parseISODate(todayISO);
  const sorted = [...deadlines].sort((a, b) => a.due.localeCompare(b.due));

  return (
    <aside className="ch-rail" aria-label="오늘 놓치면 안 되는 것">
      <header className="ch-rail-head">
        <h2>오늘 놓치면 안 되는 것</h2>
        <span className="ch-rail-date">{formatMonthDay(todayISO)}</span>
      </header>
      <div className="ch-rail-cards">
        {sorted.map((item) => {
          const dday = diffInDays(today, parseISODate(item.due));
          return (
            <article key={item.id} className={`ch-card ch-card--${urgencyOf(dday)}`}>
              <span className="ch-dchip">{dday <= 0 ? "D-DAY" : `D-${dday}`}</span>
              <h3>{item.title}</h3>
              <p className="ch-card-meta">{item.meta}</p>
              {item.note && <p className="ch-card-note">{item.note}</p>}
              <button type="button" className="ch-card-action">
                {item.actionLabel}
              </button>
            </article>
          );
        })}
      </div>
    </aside>
  );
}

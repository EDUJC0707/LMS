import { useState } from "react";

import { addDays, diffInDays, parseISODate, toISODate, WEEKDAY_KO } from "./dates";
import type { AttendanceStatus, CurriculumWeek, StudentHomeData } from "./types";

/* 출결 도장 — 실제 도장처럼 날짜마다 기울기가 조금씩 다르다(날짜 기반 고정값) */
function Stamp({ status, day }: { status: AttendanceStatus; day: number }) {
  const tilt = ((day * 47) % 11) - 5; // -5° ~ +5°
  return (
    <span
      className={`ch-stamp ch-stamp--${status}`}
      style={{ transform: `rotate(${tilt}deg)` }}
      aria-hidden="true"
    >
      {status === "present" ? "출석" : "결석"}
    </span>
  );
}

function Chevron() {
  return (
    <svg className="ch-chevron" width="10" height="6" viewBox="0 0 10 6" aria-hidden="true">
      <path
        d="M1 1l4 4 4-4"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

interface WeekRowProps {
  week: CurriculumWeek;
  data: StudentHomeData;
  open: boolean;
  onToggle: () => void;
}

function WeekRow({ week, data, open, onToggle }: WeekRowProps) {
  const today = parseISODate(data.today);
  const start = parseISODate(week.start);
  const isCurrent = week.index === data.course.currentWeek;
  const todayPlanDay = isCurrent ? today.getDay() : 0; // Day 1(월)~6(토), 일요일이면 없음
  const panelId = `ch-weekpanel-${week.index}`;

  const days = Array.from({ length: 7 }, (_, i) => {
    const date = addDays(start, i);
    const iso = toISODate(date);
    const inMonth = date.getMonth() === data.month - 1;
    const status = data.attendance[iso];
    const offset = diffInDays(today, date);
    const isToday = offset === 0;
    const isUpcomingClass = data.classWeekdays.includes(date.getDay()) && offset >= 0;
    return { date, iso, inMonth, status, isToday, isUpcomingClass };
  });

  return (
    <div className="ch-weekblock">
      <div className="ch-week">
        <button
          type="button"
          className={`ch-gutter${open ? " is-open" : ""}${isCurrent ? " is-current" : ""}`}
          aria-expanded={open}
          aria-controls={open ? panelId : undefined}
          onClick={onToggle}
        >
          <span className="ch-gutter-course">{data.course.name}</span>
          <span className="ch-gutter-week">
            {week.index}주차 <Chevron />
          </span>
          {isCurrent && <span className="ch-now-pill">이번 주</span>}
        </button>

        {days.map((d) => {
          const statusLabel =
            d.status === "present" ? "출석" : d.status === "absent" ? "결석" : null;
          const label = `${d.date.getMonth() + 1}월 ${d.date.getDate()}일${
            statusLabel ? ` ${statusLabel}` : ""
          }${d.isToday ? " 오늘" : ""}`;
          return (
            <div
              key={d.iso}
              className={`ch-day${d.inMonth ? "" : " ch-day--out"}${d.isToday ? " ch-day--today" : ""}`}
              aria-label={label}
            >
              <span className="ch-day-num">{d.date.getDate()}</span>
              {d.status && <Stamp status={d.status} day={d.date.getDate()} />}
              {!d.status && d.isUpcomingClass && d.inMonth && (
                <span className="ch-day-class">수업</span>
              )}
            </div>
          );
        })}
      </div>

      {open && (
        <div className="ch-weekpanel" id={panelId}>
          {week.notice && (
            <p className="ch-notice">
              <span className="ch-notice-badge">주차 공지</span>
              {week.notice}
            </p>
          )}
          <ul className="ch-plans">
            {week.plans.map((plan) => {
              const isTodayPlan = plan.day === todayPlanDay;
              return (
                <li key={plan.day} className={`ch-plan${isTodayPlan ? " ch-plan--today" : ""}`}>
                  <span className="ch-plan-day">DAY {plan.day}</span>
                  <span className="ch-plan-title">{plan.title}</span>
                  {isTodayPlan && <span className="ch-plan-todaychip">오늘</span>}
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}

export default function MonthCalendar({ data }: { data: StudentHomeData }) {
  const [openWeek, setOpenWeek] = useState<number | null>(data.course.currentWeek);

  const monthPrefix = `${data.year}-${String(data.month).padStart(2, "0")}-`;
  const monthAttendance = Object.entries(data.attendance).filter(([iso]) =>
    iso.startsWith(monthPrefix),
  );
  const presentCount = monthAttendance.filter(([, s]) => s === "present").length;
  const absentCount = monthAttendance.filter(([, s]) => s === "absent").length;
  const progress = Math.round((data.course.currentWeek / data.course.totalWeeks) * 100);

  return (
    <section className="ch-cal" aria-label="월간 캘린더">
      <header className="ch-cal-head">
        <h1 className="ch-cal-title">
          <span className="ch-cal-month">{data.month}월</span>
          <span className="ch-cal-year">{data.year}</span>
        </h1>
        <p className="ch-cal-att">
          이번 달{" "}
          <span className="ch-ministamp ch-ministamp--present" aria-hidden="true">
            출
          </span>
          <em className="ch-att-present">출석 {presentCount}</em> ·{" "}
          <span className="ch-ministamp ch-ministamp--absent" aria-hidden="true">
            결
          </span>
          <em className="ch-att-absent">결석 {absentCount}</em>
        </p>
        <div className="ch-progress">
          <p className="ch-progress-label">
            {data.course.name} <strong>{data.course.currentWeek}주차</strong> /{" "}
            {data.course.totalWeeks}주
          </p>
          <div
            className="ch-progress-track"
            role="progressbar"
            aria-valuenow={data.course.currentWeek}
            aria-valuemin={1}
            aria-valuemax={data.course.totalWeeks}
            aria-label="커리큘럼 진행"
          >
            <div className="ch-progress-fill" style={{ width: `${progress}%` }} />
          </div>
        </div>
      </header>

      <div className="ch-grid-head" aria-hidden="true">
        <span className="ch-dow ch-dow--gutter">주차</span>
        {WEEKDAY_KO.map((name, i) => (
          <span
            key={name}
            className={`ch-dow${i === 0 ? " ch-dow--sun" : ""}${i === 6 ? " ch-dow--sat" : ""}`}
          >
            {name}
          </span>
        ))}
      </div>

      {data.weeks.map((week) => (
        <WeekRow
          key={week.index}
          week={week}
          data={data}
          open={openWeek === week.index}
          onToggle={() => setOpenWeek(openWeek === week.index ? null : week.index)}
        />
      ))}
    </section>
  );
}

import DeadlineRail from "./DeadlineRail";
import MonthCalendar from "./MonthCalendar";
import { studentHomeData } from "./mockData";
import "./calendarHome.css";

/* 학생 캘린더 홈 (PRD 3.2.0) — 로그인 직후 첫 화면.
   출결 도장 · 주차별 커리큘럼 · 주 단위 학습계획 · 마감 임박 카드를 한 화면에. */
export default function CalendarHome() {
  return (
    <div className="ch-layout">
      <MonthCalendar data={studentHomeData} />
      <DeadlineRail deadlines={studentHomeData.deadlines} todayISO={studentHomeData.today} />
    </div>
  );
}

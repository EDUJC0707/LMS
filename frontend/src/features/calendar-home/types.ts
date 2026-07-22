export type AttendanceStatus = "present" | "absent";

export interface DayPlan {
  /** 주 내 학습일 순번 — Day 1(월) ~ Day 6(토) */
  day: number;
  title: string;
}

export interface CurriculumWeek {
  /** 커리큘럼 주차 (1부터) */
  index: number;
  /** 달력 행 시작일(일요일), ISO */
  start: string;
  /** 주차 공지 — 해당 주 오프라인 특이사항 */
  notice?: string;
  plans: DayPlan[];
}

export type DeadlineKind = "clinic" | "video" | "payment";

export interface Deadline {
  id: string;
  kind: DeadlineKind;
  title: string;
  meta: string;
  note?: string;
  /** 마감일 ISO — D-n 계산 기준 */
  due: string;
  actionLabel: string;
}

export interface StudentHomeData {
  student: { name: string; className: string };
  course: { name: string; totalWeeks: number; currentWeek: number };
  /** 데모 기준일 ISO */
  today: string;
  /** 캘린더 표시 연·월 (month는 1부터) */
  year: number;
  month: number;
  /** 수업 요일 (0=일 … 6=토) */
  classWeekdays: number[];
  /** 날짜별 출결 — key: ISO date */
  attendance: Record<string, AttendanceStatus>;
  weeks: CurriculumWeek[];
  deadlines: Deadline[];
}

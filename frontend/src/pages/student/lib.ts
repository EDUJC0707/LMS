/**
 * 학생 화면 공용 타입·헬퍼.
 *
 * 타입은 실제 서버 응답(2026-07-28 curl 실측 + backend/apps/*)에 맞춘 계약이다.
 * ⚠ 역할·상태별로 **없는 키는 아예 내려오지 않는다**(빈 배열이 아니라 undefined).
 *   예: 예비등록 학생의 /api/student/home 은 calendar·deadlines·course 가 없고
 *       purchasable_products 만 온다. 화면은 서버가 안 준 것을 만들어내지 않는다.
 */

/* ── 요일 ──────────────────────────────────────────────────────────────
   백엔드 축은 0=일 … 6=토 (clinic.models.ClinicSlot.weekday,
   curriculum.models.ClassEnrollment.primary_weekday 주석). */
export const WEEKDAY_LABELS = ["일", "월", "화", "수", "목", "금", "토"] as const;

export function weekdayName(no: number | null | undefined): string {
  if (no === null || no === undefined) return "-";
  return WEEKDAY_LABELS[no] ?? String(no);
}

/* ── 월(YYYY-MM) 계산 ─────────────────────────────────────────────── */

export function currentMonth(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

export function shiftMonth(month: string, delta: number): string {
  const [year, monthNo] = month.split("-").map(Number);
  const date = new Date(year, monthNo - 1 + delta, 1);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
}

/** "2026-07" → "2026년 7월" */
export function monthLabel(month: string): string {
  const [year, monthNo] = month.split("-");
  return `${year}년 ${Number(monthNo)}월`;
}

/** 해당 월의 주 단위 격자. 빈 칸은 null. */
export function monthGrid(month: string): (string | null)[][] {
  const [year, monthNo] = month.split("-").map(Number);
  const first = new Date(year, monthNo - 1, 1);
  const daysInMonth = new Date(year, monthNo, 0).getDate();
  const cells: (string | null)[] = Array(first.getDay()).fill(null);
  for (let day = 1; day <= daysInMonth; day += 1) {
    cells.push(`${month}-${String(day).padStart(2, "0")}`);
  }
  while (cells.length % 7 !== 0) cells.push(null);
  const rows: (string | null)[][] = [];
  for (let i = 0; i < cells.length; i += 7) rows.push(cells.slice(i, i + 7));
  return rows;
}

/* ── 표시 서식 ─────────────────────────────────────────────────────── */

/** 소수 둘째 자리 이하를 버리고 불필요한 0 을 없앤다. 없으면 "—". */
export function num(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const fixed = value.toFixed(digits);
  return fixed.replace(/\.0+$/, "").replace(/(\.\d*[1-9])0+$/, "$1");
}

export function won(value: number): string {
  return `${value.toLocaleString("ko-KR")}원`;
}

/** "2026-07-29" → "7월 29일(수)". 로컬 날짜로 만든다(UTC 파싱으로 하루 밀리지 않게). */
export function dayLabel(iso: string): string {
  const [year, monthNo, dayNo] = iso.split("-").map(Number);
  const date = new Date(year, monthNo - 1, dayNo);
  return `${monthNo}월 ${dayNo}일(${weekdayName(date.getDay())})`;
}

/** ISO 일시 → "7월 29일 21:47" */
export function dateTimeLabel(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const time = `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
  return `${date.getMonth() + 1}월 ${date.getDate()}일 ${time}`;
}

/** D-day 를 사람 말로. 0 = 오늘, null = 기한 없음. */
export function ddayLabel(dDay: number | null | undefined): string {
  if (dDay === null || dDay === undefined) return "기한 없음";
  if (dDay === 0) return "오늘";
  if (dDay < 0) return `${-dDay}일 지남`;
  return `D-${dDay}`;
}

/* ── /api/student/home ────────────────────────────────────────────── */

export interface HomeStudent {
  student_id: number;
  name: string;
  current_class: string | null;
  enrollment_status: string;
}

export interface HomeCourse {
  course_id: number;
  name: string;
  class_name: string | null;
  total_weeks: number;
  current_week: number | null;
  class_weekdays: number[];
}

export interface CalendarDay {
  date: string;
  attendance: string | null; // "출석" | "지각" | "결석" | null
  has_class_session: boolean;
}

export interface DayPlan {
  day_no: number;
  title: string;
  content: string;
}

/** 잠긴 주차는 week_no·locked 만 온다 — 제목·날짜·계획을 상상해 채우지 않는다. */
export interface LockedWeek {
  week_no: number;
  locked: true;
}

export interface OpenWeek {
  week_no: number;
  locked: false;
  label: string;
  title: string;
  start_date: string;
  end_date: string;
  offline_notice: string | null;
  day_plans: DayPlan[];
}

export type CurriculumWeek = LockedWeek | OpenWeek;

export interface CalendarBlock {
  days: CalendarDay[];
  weeks: CurriculumWeek[];
}

export interface ClinicDeadline {
  kind: "클리닉";
  due_date: string | null;
  d_day: number | null;
  clinic_id: number;
  date: string;
  start_time: string;
  link_active: boolean;
}

export interface VideoDeadline {
  kind: "영상만료";
  due_date: string | null;
  d_day: number | null;
  grant_id: number;
  course_name: string;
  week_no: number;
  expires_at: string;
}

export interface PaymentDeadline {
  kind: "교재결제";
  due_date: string | null;
  d_day: number | null;
  order_id: number;
  product_name: string;
  amount: number;
}

export type Deadline = ClinicDeadline | VideoDeadline | PaymentDeadline;

export interface Product {
  product_id: number;
  name: string;
  price: number;
}

export interface StudentHome {
  student: HomeStudent;
  month: string;
  today: string;
  /** 등록 학생만. 예비등록·퇴원에는 아예 없다. */
  course?: HomeCourse | null;
  calendar?: CalendarBlock;
  deadlines?: Deadline[];
  /** 예비등록 학생에게만 내려온다. */
  purchasable_products?: Product[];
}

/* ── /api/student/grades ──────────────────────────────────────────── */

export interface GradeStudent {
  student_id: number;
  name: string;
  unique_id: string;
  school: string | null;
  current_class: string | null;
}

export interface ExamRow {
  exam_id: number;
  name: string;
  exam_date: string;
  round_no: number | null;
  is_taken: boolean;
  my_score: number | null;
  max_score: number | null;
  average: number | null;
}

export interface TrendPoint extends ExamRow {
  percentile: number | null;
  top30_score: number | null;
  highest_score: number | null;
}

export interface GradeList {
  student: GradeStudent;
  exams: ExamRow[];
  trend: TrendPoint[];
}

/* ── /api/student/grades/{exam_id} ────────────────────────────────── */

export interface ReportSummary {
  my_score: number;
  max_score: number;
  average: number;
  stddev: number;
  highest_score: number;
  top30_score: number;
  percentile: number;
}

export interface ReportUnit {
  unit_major: string;
  question_count: number;
  correct_count: number;
  wrong_count: number;
  my_points: number;
  unit_max_points: number;
  correct_rate: number;
}

export interface ReportQuestion {
  q_number: number;
  unit_major: string;
  unit_minor: string | null;
  points: number;
  answer: string;
  marked: string | null;
  result: string | null; // "정답" | "오답" | "무응답"
  wrong_rate: number | null;
}

export interface WrongAnswerGuide {
  q_number: number;
  unit_major: string;
  theme_tag: string | null;
  study_guide: string;
  guide_video: { video_id: number; title: string } | null;
}

export interface ThemeTrendPoint {
  exam_id: number;
  name: string;
  exam_date: string;
  round_no: number | null;
  correct: number;
  total: number;
  rate: number;
  cumulative_correct: number;
  cumulative_total: number;
  cumulative_rate: number;
}

export interface ThemeTrend {
  theme: string;
  points: ThemeTrendPoint[];
}

export interface GradeReport {
  student: GradeStudent;
  exam: {
    exam_id: number;
    name: string;
    exam_date: string;
    round_no: number | null;
    notice: string | null;
  };
  is_taken: boolean;
  report: {
    summary: ReportSummary;
    units: ReportUnit[];
    questions: ReportQuestion[];
    wrong_answer_guides: WrongAnswerGuide[];
    theme_trends: ThemeTrend[];
  } | null;
}

/* ── /api/student/clinic ──────────────────────────────────────────── */

export interface ClinicSlot {
  slot_id: number;
  weekday: number;
  start_time: string;
  end_time: string;
  capacity: number;
  next_date: string;
  remaining: number;
  is_full: boolean;
}

export interface ClinicRequestRow {
  clinic_id: number;
  exam_id: number;
  slot_id: number;
  status: string; // "대기" | "승인배정" | "취소" | "완료" …
  requested_date: string;
  requested_time: string;
  cancelled_at: string | null;
  link_active: boolean;
  meet_url: string | null;
}

export interface ClinicPayload {
  exam: { exam_id: number; name: string; exam_date: string };
  eligibility: { is_target: boolean; reason: string | null };
  clinic_banned: boolean;
  my_requests: ClinicRequestRow[];
  /** 대상자가 아니면 슬롯 목록 자체가 내려오지 않는다(상태 기반 노출). */
  slots?: ClinicSlot[];
}

/* ── /api/student/workbook ────────────────────────────────────────── */

export interface WorkbookRow {
  submission_id: number;
  session: { session_id: number; session_date: string; session_no: number | null } | null;
  image_url: string;
  performance_grade: string | null;
  assignment_done: boolean | null;
  uploaded_at: string;
}

export interface WorkbookPayload {
  workbooks: WorkbookRow[];
}

/* ── /api/student/makeup-request ──────────────────────────────────── */

export interface MakeupResult {
  makeup_id: number;
  student_id: number;
  attendance_id: number;
  source: string;
  status: string;
  session_date: string | null;
  week_no: number | null;
  course_name: string | null;
  granted_at: string | null;
  created_at: string | null;
}

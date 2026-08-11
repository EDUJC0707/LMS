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
  attendance: string | null; // "출석" | "결석" | "결석(동보)" | "결석(현보)" | null
  /** 출결 레코드 PK. null = 그날 출결 기록 없음. 동보 신청 body 의 키가 그대로 이 값이다. */
  attendance_id: number | null;
  /** null = 동보 미신청. 그 외 신청 · 승인 · 지급완료 · 거절 */
  makeup_status: string | null;
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
  /** 원번(유일). 화면에 보이는 번호. 계정 미발급이면 null */
  login_id: string | null;
  /** 지면 대조 전용 키. 중복될 수 있어 사람을 특정하지 못한다 */
  matching_key: string;
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

/**
 * 시간 한 칸. 정원·잔여석은 계약에 없다 — 한 타임 1명 고정이라
 * 잔여석이 늘 1이고, 그 사실은 `available` 하나로 전부 표현된다.
 */
export interface AvailabilityTime {
  slot_id: number;
  start_time: string;
  end_time: string;
  available: boolean;
  /** 불가 사유. "마감" = 남이 찼다 · "내신청" = 내 활성 신청이 그 칸이다. */
  reason: string | null;
}

export interface AvailabilityDay {
  date: string;
  /** 0=일 … 6=토 (JS Date.getDay() 와 같은 축). */
  weekday: number;
  times: AvailabilityTime[];
}

/**
 * GET /api/student/clinic/availability?exam_id=&from=&to=
 *
 * ⚠ 쿼리 키는 `from`·`to` 다(`date_from` 아님 — clinic/views.py 실측).
 * `days` 에는 **예약 가능한 날만** 담긴다: 지난 날짜·오늘(당일 신청 불가라
 * 시각과 무관)·**신청 창구 끝(시험 주 다음 월요일) 이후**·활성 슬롯이 없는
 * 요일은 아예 빠진다. 그래서 달력은 "이 날짜가 days 에 있나"로만 생사를
 * 판정한다 — 죽이는 규칙을 화면이 따로 갖지 않는다.
 * 창구가 지났으면 `days` 가 비고 `range.to` 가 `range.from` 보다 앞선다
 * (403 이 아니다 — 자격은 있는데 기간이 끝난 것).
 * 자격이 없거나 노쇼 제한이면 403 — 시간표 자체를 못 본다.
 */
export interface ClinicAvailability {
  exam_id: number;
  range: { from: string; to: string };
  days: AvailabilityDay[];
}

/**
 * 창구가 지났는가 — 서버는 403 이 아니라 **뒤집힌 구간**으로 말한다
 * (자격은 그대로인데 기간만 끝난 것이라 비대상과 다른 사실이다).
 * 시작(내일)이 끝(시험 주 다음 월요일)을 넘어서면 창구가 지난 것이다.
 */
export function windowClosed(range: { from: string; to: string }): boolean {
  return range.to < range.from;
}

/** 달력이 설 달과, 좌우 화살표가 갈 수 있는 양 끝. */
export interface CalendarMonths {
  month: string;
  first: string;
  last: string;
}

/**
 * 달력의 달 — 창구가 걸친 달 밖으로는 나가지 않는다.
 *
 * 창구는 길어야 7일(내일~시험 주 다음 월요일)이라 걸치는 달은 많아야 둘이다.
 * 그래서 화살표를 열어 두면 학생이 고를 게 하나도 없는 달을 계속 넘기게 된다 —
 * 끝을 화살표의 생사로 말한다(칸의 생사와 같은 어법).
 *
 * `picked` 는 학생이 화살표로 넘긴 달(null = 아직 안 넘겼다). 처음 열 달은
 * **고를 게 있는 첫 달**이다: 창구가 달을 넘겨 걸치면(7/31 시험 → 8/3 만 열림)
 * 이번 달로 열어 봐야 전부 죽은 칸이다.
 */
export function calendarMonths(
  avail: ClinicAvailability,
  picked: string | null,
): CalendarMonths {
  const open = avail.days;
  const first = (open[0]?.date ?? avail.range.from).slice(0, 7);
  const last = (open[open.length - 1]?.date ?? avail.range.from).slice(0, 7);
  const month = picked === null || picked < first ? first : picked > last ? last : picked;
  return { month, first, last };
}

/** 시간 열이 그릴 것 — 고를 날짜가 없다 / 그 날은 닫혔다 / 시간 목록. */
export type TimeColumnView =
  | { kind: "no-date" }
  | { kind: "closed"; date: string }
  | { kind: "open"; date: string; times: AvailabilityTime[] };

/**
 * 고른 날짜가 `days` 밖일 수 있다 — 전날 마감으로 오늘이 응답에서 빠진 뒤
 * 오늘로 잡힌 예약을 [시간 변경]으로 열면 화면은 그 예약의 날짜를 고른다.
 * 그때 `closed` 를 돌려주지 않으면 시간 열이 날짜만 쓰고 아래를 비운 채
 * 멈춘다 — 눌렀는데 아무 말도 없는 화면이 된다.
 */
export function timeColumn(days: AvailabilityDay[], date: string | null): TimeColumnView {
  if (date === null) return { kind: "no-date" };
  const day = days.find((entry) => entry.date === date);
  if (!day || day.times.length === 0) return { kind: "closed", date };
  return { kind: "open", date, times: day.times };
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
  conference_url: string | null;
}

/**
 * GET /api/student/clinic?exam_id= — 자격 판정과 내 신청 현황만.
 * 시간표는 여기 없다(→ ClinicAvailability).
 */
export interface ClinicPayload {
  exam: { exam_id: number; name: string; exam_date: string };
  /** reason 은 대상이 아닐 때만: 결석 · 미응시 · 평균이상. */
  eligibility: { is_target: boolean; reason: string | null };
  clinic_banned: boolean;
  my_requests: ClinicRequestRow[];
  /** 지난 신청 전부 — **회차를 가리지 않는다**(최신 먼저). 회차 선택 드롭다운을
   *  뺐기 때문에(2026-08-11) 줄마다 `exam_name` 이 붙어 온다. */
  history: (ClinicRequestRow & { exam_name: string | null })[];
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

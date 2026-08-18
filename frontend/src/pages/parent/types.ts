/**
 * 학부모 화면이 받는 서버 응답 모양.
 *
 * 2026-07-28 실제 서버(localhost:8000)에 학부모 계정으로 호출해 확인한 계약이며,
 * 없는 키는 아예 내려오지 않으므로 전부 옵셔널로 다룬다(상태 기반 노출, PRD §4).
 *   GET /api/parent/home?student_id=&month=
 *   GET /api/parent/grades[?student_id=]      GET /api/parent/grades/{exam_id}
 *   GET /api/parent/workbook?student_id=      POST /api/parent/makeup-request
 */

/* ── 홈(캘린더) ──────────────────────────────────────────────────── */

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
  /** 0=일 … 6=토 */
  class_weekdays: number[];
}

export interface HomeDay {
  date: string;
  /** 출석 · 결석 · 결석(동보) · 결석(현보). 아직 입력 전이면 null */
  attendance: string | null;
  /** 출결 레코드 PK. 기록이 없으면 null */
  attendance_id: number | null;
  /** null = 동보 미신청. 그 외 신청 · 승인 · 지급완료 · 거절 */
  makeup_status: string | null;
  has_class_session: boolean;
}

export interface HomeDayPlan {
  day_no: number;
  title: string;
  content: string;
}

export interface HomeWeek {
  week_no: number;
  /** 잠긴 주차는 제목·날짜·계획이 통째로 빠진다 */
  locked: boolean;
  label?: string;
  title?: string;
  start_date?: string;
  end_date?: string;
  offline_notice?: string | null;
  day_plans?: HomeDayPlan[];
}

export interface DeadlineBase {
  kind: string;
  due_date: string | null;
  d_day: number | null;
}

export interface ClinicDeadline extends DeadlineBase {
  kind: "클리닉";
  clinic_id: number;
  date: string;
  start_time: string;
  link_active: boolean;
}

export interface VideoDeadline extends DeadlineBase {
  kind: "영상만료";
  grant_id: number;
  course_name: string;
  week_no: number;
  expires_at: string;
}

export interface PaymentDeadline extends DeadlineBase {
  kind: "교재결제";
  order_id: number;
  product_name: string;
  amount: number;
}

export type Deadline = ClinicDeadline | VideoDeadline | PaymentDeadline | DeadlineBase;

export interface PaymentRow {
  order_id: number;
  product_name: string;
  amount: number;
  /** 결제완료 · 미결제 */
  status: string;
  is_billed: boolean;
  billed_at: string | null;
  paid_at: string | null;
}

export interface AbsenceRow {
  date: string;
  /** null = 동보 미신청. 그 외 신청·승인·지급완료·거절 */
  makeup_status: string | null;
  /** 동보 신청 POST 가 요구하는 출결 번호. 결석 항목이므로 항상 값이 있다. */
  attendance_id: number;
}

export interface PurchasableProduct {
  product_id: number;
  name: string;
  /** 세트 · 낱개 (FLOW 1-6). 포함 관계는 서버도 모른다 — 표시뿐이다. */
  kind: string;
  price: number;
}

export interface ParentHome {
  student: HomeStudent;
  month: string;
  today: string;
  course?: HomeCourse | null;
  /** 미등록(예비등록)·퇴원 자녀에게는 캘린더 자체가 없다 */
  calendar?: { days: HomeDay[]; weeks: HomeWeek[] } | null;
  deadlines?: Deadline[];
  payment_status?: PaymentRow[];
  absences?: AbsenceRow[];
  purchasable_products?: PurchasableProduct[];
}

/* ── 성적 ────────────────────────────────────────────────────────── */

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

export interface TrendPoint {
  exam_id: number;
  name: string;
  exam_date: string;
  round_no: number | null;
  is_taken: boolean;
  my_score: number | null;
  percentile: number | null;
  average: number | null;
  top30_score: number | null;
  highest_score: number | null;
}

export interface GradeList {
  student: GradeStudent;
  exams: ExamRow[];
  trend: TrendPoint[];
}

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
  /** 정답 · 오답 · 무응답 */
  result: string | null;
  wrong_rate: number | null;
}

export interface ReportGuide {
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

export interface GradeReportPayload {
  student: GradeStudent;
  exam: {
    exam_id: number;
    name: string;
    exam_date: string;
    round_no: number | null;
    notice: string | null;
  };
  is_taken: boolean;
  /** 미응시면 null — 성적표를 만들지 않는다(PRD 3.1.1) */
  report: {
    summary: ReportSummary;
    units: ReportUnit[];
    questions: ReportQuestion[];
    wrong_answer_guides: ReportGuide[];
    theme_trends: ThemeTrend[];
  } | null;
  message?: string;
}

/* ── 워크북 ──────────────────────────────────────────────────────── */

export interface WorkbookRow {
  submission_id: number;
  session: { session_id: number; session_date: string; session_no: number | null } | null;
  image_url: string;
  performance_grade: string | null;
  assignment_done: boolean | null;
  uploaded_at: string;
}

export interface WorkbookList {
  workbooks: WorkbookRow[];
}

/* ── 동보(보강 영상) 신청 ────────────────────────────────────────── */

export interface MakeupBlock {
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

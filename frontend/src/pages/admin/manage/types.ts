/**
 * 관리자 · 관리 화면이 쓰는 서버 응답 타입.
 *
 * 전부 실제 응답(localhost:8000)에서 받아 적은 것이다 — 추측한 필드가 없다.
 * 필드가 null 로 내려올 수 있는 자리는 전부 `| null` 로 표시해 뒀다.
 */

/* ── /api/admin/staff ─────────────────────────────────────────────── */

export interface StaffRow {
  user_id: number;
  login_id: string;
  name: string;
  role: string;
  is_active: boolean;
  /** 역할 프리셋으로 자동 부여되는 기능 */
  preset: string[];
  /** 프리셋과의 편차 — added=개별 부여, removed=개별 회수 */
  delta: { added: string[]; removed: string[] };
  /** 실제로 열리는 기능 = 프리셋 ⊕ delta */
  effective: string[];
}

export interface StaffMatrix {
  feature_keys: string[];
  staff: StaffRow[];
}

/** POST /api/admin/staff 응답 — matrix_row + 초기 비밀번호(1회) */
export interface StaffCreated extends StaffRow {
  initial_password: string;
}

/* ── /api/admin/accounts/bulk ─────────────────────────────────────── */

export interface BulkParentBlock {
  created: boolean;
  login_id: string | null;
  initial_password?: string | null;
}

export interface BulkResultRow {
  index: number;
  name: string | null;
  status: "생성" | "실패";
  login_id?: string;
  initial_password?: string;
  student_id?: number;
  /** 서버가 이름·휴대폰에서 만든 원번(입력값이 아니다). */
  unique_id?: string;
  parent?: BulkParentBlock | null;
  error?: string;
}

export interface BulkResult {
  results: BulkResultRow[];
  summary: {
    created: number;
    failed: number;
    parents_created: number;
    parents_linked: number;
  };
}

export interface RegisterResult {
  student_id: number;
  enrollment_status: string;
  registered_at: string;
}

/* ── /api/admin/attendance/sessions (예비등록 명단·워크북 회차 선택용) ── */

export interface SessionRow {
  session_id: number;
  session_date: string;
  session_no: number | null;
  target_grade: number | null;
  memo: string | null;
  week_no: number | null;
  course: { course_id: number; name: string } | null;
}

export interface RosterStudent {
  student_id: number;
  name: string;
  unique_id: string;
  current_class: string | null;
  enrollment_status: string;
  attendance: {
    status: string | null;
    exam_taken: boolean;
    marked_at: string | null;
    updated_at: string | null;
  } | null;
}

export interface SessionDetail {
  session: SessionRow;
  students: RosterStudent[];
}

/* ── /api/admin/clinic/* ──────────────────────────────────────────── */

export type ClinicStatus = "대기" | "승인배정" | "미승인" | "취소";

export interface ClinicRequestRow {
  clinic_id: number;
  student: {
    student_id: number;
    name: string | null;
    unique_id: string;
    noshow_count: number;
    clinic_banned: boolean;
  };
  exam_id: number | null;
  slot_id: number | null;
  requested_date: string;
  requested_time: string;
  status: ClinicStatus;
  assigned_staff: { user_id: number; name: string } | null;
  meet_url: string | null;
  attendance_status: "출석" | "결석" | null;
}

export interface ClinicCriteria {
  criteria_id: number;
  item: string;
  description: string | null;
  display_order: number | null;
}

/* ── /api/admin/exams ─────────────────────────────────────────────── */

export interface ExamListRow {
  exam_id: number;
  name: string;
  exam_date: string;
  round_no: number | null;
  target_grade: number | null;
  taker_count: number;
  score_count: number;
  average: number | null;
  processing_status: string;
  pending_sheet_count: number;
}

export interface ExamStudentRow {
  student_id: number;
  name: string;
  unique_id: string;
  current_class: string | null;
  total_score: number | null;
  max_score: number | null;
  percentile: number | null;
  is_taken: boolean;
  rank: number | null;
}

export interface ExamQuestionRow {
  question_id: number;
  q_number: number;
  unit_major: string | null;
  unit_minor: string | null;
  points: number | null;
  answer: string | null;
  answered_count: number;
  correct_count: number;
  wrong_count: number;
  blank_count: number;
  multi_count: number;
  correct_rate: number | null;
}

export interface ExamDetail {
  exam: {
    exam_id: number;
    name: string;
    exam_date: string;
    round_no: number | null;
    target_grade: number | null;
    notice: string | null;
  };
  stats: {
    taker_count: number;
    score_count: number;
    average: number | null;
    stddev: number | null;
    highest_score: number | null;
    top30_score: number | null;
    processing_status: string;
    pending_sheet_count: number;
  };
  students: ExamStudentRow[];
  questions: ExamQuestionRow[];
}

/* ── /api/admin/workbook ──────────────────────────────────────────── */

export type WorkbookStatus = "대기" | "자동매칭" | "수동확정" | "불일치" | "인식실패";

export interface WorkbookRow {
  submission_id: number;
  student: { student_id: number; name: string | null; unique_id: string };
  session: { session_id: number; session_date: string; session_no: number | null } | null;
  image_url: string;
  recognized_unique_id: string | null;
  recognized_name: string | null;
  /** null 이면 아직 대조 전(=대기) */
  match_status: WorkbookStatus | null;
  performance_grade: string | null;
  uploaded_by: { user_id: number; name: string } | null;
  uploaded_at: string;
}

export interface WorkbookList {
  submissions: WorkbookRow[];
  total_count: number;
  unmatched_count: number;
}

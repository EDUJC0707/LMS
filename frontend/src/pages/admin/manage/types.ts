/**
 * 관리자 · 관리 화면이 쓰는 서버 응답 타입.
 *
 * 전부 실제 응답(localhost:8000)에서 받아 적은 것이다 — 추측한 필드가 없다.
 * 필드가 null 로 내려올 수 있는 자리는 전부 `| null` 로 표시해 뒀다.
 */
// 타입만 가져온다(런타임 순환 없음) — 명부 행 모양은 directory 가 원본이다.
import type { DirectoryStudent } from "./directory";

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

/* ── /api/admin/classes ───────────────────────────────────────────── */

export interface ClassRow {
  class_id: number;
  course_id: number;
  course_name: string;
  name: string;
  /** 개강일. 반을 만들 때 받지만 옛 반은 비어 있다. */
  start_date: string | null;
  /** 이 반이 가진 회차 수 = 반의 주차 수(커리 총주차와 다를 수 있다). */
  week_count: number;
  /** 오늘까지 지난 회차 수. */
  current_week: number;
  student_count: number;
}

export interface CourseGroup {
  course_id: number;
  name: string;
  total_weeks: number;
  classes: ClassRow[];
}

export interface ClassList {
  courses: CourseGroup[];
}

/* ── /api/admin/accounts/bulk ─────────────────────────────────────── */

export interface BulkParentBlock {
  created: boolean;
  login_id: string | null;
  initial_password?: string | null;
}

/** 확인필요 행에 걸린 학생 — 조교가 오타인지 형제인지 가릴 값들(FLOW 2-3). */
export interface BulkMatchedStudent {
  student_id: number;
  name: string;
  login_id: string;
  phone: string;
  parent_phone: string;
}

export interface BulkResultRow {
  index: number;
  name: string | null;
  /** 기존 = 이미 계정이 있어 수강만 추가된 행(FLOW 2-4 — 안내가 안 나간다).
   *  확인필요 = 번호가 하나만 맞아 아무것도 만들지 않은 행(FLOW 2-3). */
  status: "생성" | "기존" | "확인필요" | "실패";
  login_id?: string;
  initial_password?: string;
  student_id?: number;
  /** 서버가 이름·휴대폰에서 만든 원번(입력값이 아니다). */
  matching_key?: string;
  matched?: BulkMatchedStudent[];
  parent?: BulkParentBlock | null;
  error?: string;
}

export interface BulkResult {
  results: BulkResultRow[];
  summary: {
    created: number;
    existing: number;
    needs_review: number;
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
  /** 원번(유일). 화면에 보이는 번호. 계정 미발급이면 null */
  login_id: string | null;
  /** 지면 대조 전용 키. 중복될 수 있어 사람을 특정하지 못한다 */
  matching_key: string;
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
    /** 원번(유일). 화면에 보이는 번호. 계정 미발급이면 null */
    login_id: string | null;
    /** 지면 대조 전용 키. 중복될 수 있어 사람을 특정하지 못한다 */
    matching_key: string;
    noshow_count: number;
    clinic_banned: boolean;
  };
  exam_id: number | null;
  slot_id: number | null;
  requested_date: string;
  requested_time: string;
  status: ClinicStatus;
  assigned_staff: { user_id: number; name: string } | null;
  conference_url: string | null;
  attendance_status: "출석" | "결석" | null;
  /** 끝난 회의에서 거둔 감독 자료. 아직 없으면 null(수집 전이거나 회의 자체가 없었다). */
  supervision: { summary: string | null; transcript_url: string } | null;
}

export interface ClinicCriteria {
  criteria_id: number;
  item: string;
  description: string | null;
  display_order: number | null;
}

/* ── /api/admin/exams ─────────────────────────────────────────────── */

/** 어느 카드가 들어오는지 — 미니테스트는 답안 카드, 모의고사는 성적 조사 카드. */
export type ExamKind = "미니테스트" | "모의고사";

export interface ExamListRow {
  exam_id: number;
  name: string;
  kind: ExamKind;
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
  /** 원번(유일). 화면에 보이는 번호. 계정 미발급이면 null */
  login_id: string | null;
  /** 지면 대조 전용 키. 중복될 수 있어 사람을 특정하지 못한다 */
  matching_key: string;
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
  /** 기계가 못 읽은 줄 — 학생이 안 푼 것(무응답)과 다른 사실이다 */
  unreadable_count: number;
  correct_rate: number | null;
}

export interface ExamDetail {
  exam: {
    exam_id: number;
    name: string;
    kind: ExamKind;
    /** 만점. 모의고사에만 쓴다 — 미니테스트는 문항 배점의 합이다 */
    full_score: number | null;
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
  student: {
    student_id: number;
    name: string | null;
    /** 원번(유일). 계정 미발급이면 null */
    login_id: string | null;
    /** 지면 대조 전용 키. 중복될 수 있다 */
    matching_key: string;
  };
  session: { session_id: number; session_date: string; session_no: number | null } | null;
  image_url: string;
  recognized_matching_key: string | null;
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

/** 정답 키 한 줄. 단원은 채점에 안 쓰므로 비어 있어도 된다. */
export interface QuestionKeyRow {
  q_number: number;
  answer: string;
  points?: number;
  unit_major?: string;
  unit_minor?: string;
}

/** 정답 키 + 이미 쓴 단원 후보(대단원 하나에 중단원 여럿). */
export interface QuestionKeyPayload {
  questions: QuestionKeyRow[];
  units: Record<string, string[]>;
}

/* ── /api/admin/exams/{id}/sheets · /api/admin/sheets/{id} ────────── */

/** 보정 화면 목록의 한 장. */
export interface SheetRow {
  sheet_id: number;
  /** 대조 6분기 — 정상/부분/불일치/미존재/중복/비정상 */
  match_status: string;
  /** 사람이 확정한 장. 재판독이 덮지 않는다 */
  is_corrected: boolean;
  recognized_name: string | null;
  recognized_matching_key: string | null;
  /** 모의고사(자기보고) 전용. 미니테스트 장에서는 언제나 null */
  recognized_score: number | null;
  /** 버블이 아니라 손글씨 OCR 에서 온 점수 — 조교가 눈으로 대조해야 한다 */
  score_from_handwriting: boolean;
  /** 사람이 손대야 할 줄 수(복수마킹·판독불가). 대조가 `정상` 이어도 남는다 */
  issue_count: number;
  /** 명부(GET /admin/students)와 같은 행 모양 — 학생 선택기가 그대로 받는다 */
  student: DirectoryStudent | null;
}

export interface SheetQuestionRow {
  q_number: number;
  /** 정답 키 */
  answer: string;
  points: number;
  /** 판독된 마킹. 복수는 "1,3", 무응답·판독 없음은 null */
  marked: string | null;
  /** 정답/오답. **채점이 성립할 때만** 값이 있다 — 나머지는 null */
  result: string | null;
  /** 무응답/복수마킹/판독불가. 채점 결과와 축이 다르다 */
  issue_reason: string | null;
  /** issue_reason 이 있으면 true — 조교가 봐야 하는 줄 */
  issue: boolean;
  is_corrected: boolean;
}

/** 보정 화면 한 장 — 문항은 정답 키 전량에 그 장의 판독을 얹은 것. */
export interface SheetDetail extends SheetRow {
  questions: SheetQuestionRow[];
  total_score: number | null;
}

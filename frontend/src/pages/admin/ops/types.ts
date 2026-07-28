/**
 * 관리자 운영 화면이 쓰는 서버 응답 모양.
 * 전부 실제 응답을 확인해 옮긴 것이다(src/bare + curl 실측) — 추측 필드 없음.
 */

export type AttendanceStatus = "출석" | "결석" | "지각";
export const ATTENDANCE_STATUSES: AttendanceStatus[] = ["출석", "지각", "결석"];

export interface SessionCourse {
  course_id: number;
  name: string;
}

/** GET /api/admin/attendance/sessions 의 한 줄. 상세·PUT 응답에도 그대로 들어 있다. */
export interface SessionBlock {
  session_id: number;
  session_date: string;
  session_no: number | null;
  target_grade: number | null;
  memo: string | null;
  week_no: number | null;
  course: SessionCourse | null;
}

export interface AttendanceBlock {
  status: AttendanceStatus;
  exam_taken: boolean | null;
  marked_at: string | null;
  /** 값이 있으면 최초 입력 이후 정정된 행이다. */
  updated_at: string | null;
}

export interface RosterStudent {
  student_id: number;
  name: string | null;
  unique_id: string;
  current_class: string | null;
  enrollment_status: string;
  attendance: AttendanceBlock | null;
}

export interface AttendanceSummary {
  출석: number;
  지각: number;
  결석: number;
  미입력: number;
  total: number;
}

/** 출결 저장이 실제로 일으킨 파생 결과 — 사람이 자동화를 체감하는 지점. */
export interface AttendanceTriggers {
  video_grants_created: number;
  video_grants_reactivated: number;
  video_grants_revoked: number;
  counselings_created: number;
  counselings_removed: number;
}

export interface SessionDetail {
  session: SessionBlock;
  students: RosterStudent[];
  summary: AttendanceSummary;
  /** PUT 응답에만 들어 있다. */
  triggers?: AttendanceTriggers;
}

/** PUT /api/admin/attendance/sessions/{id} 본문 한 줄. */
export interface AttendanceEntry {
  student_id: number;
  status: AttendanceStatus;
  exam_taken: boolean | null;
}

export type MakeupStatus = "신청" | "승인" | "지급완료" | "거절";

export interface MakeupRow {
  makeup_id: number;
  student_id: number;
  attendance_id: number;
  source: string;
  status: MakeupStatus;
  session_date: string | null;
  week_no: number | null;
  course_name: string | null;
  granted_at: string | null;
  created_at: string;
  student: { student_id: number; name: string | null; unique_id: string };
  requested_by: string | null;
}

export interface VideoGrantBlock {
  grant_id: number;
  student_id: number;
  course_week_id: number;
  source: string;
  granted_at: string | null;
  expires_at: string | null;
}

export interface CounselCard {
  counsel_id: number;
  student: { student_id: number; name: string | null; unique_id: string };
  target: string;
  status: string;
  /** 이미 수행한 통화 시도 수(0부터). 3회째 미연결이면 알림톡으로 종결된다. */
  attempts: number;
  absence_date: string | null;
  created_at: string;
}

export interface CounselRecordResult {
  counsel_id: number;
  status: string;
  attempts: number;
  next_counsel_id: number | null;
  closed_by_sms: boolean;
  makeup_requested: boolean;
}

/** 학부모 1차 통화 최대 시도 횟수 — 백엔드 counseling.MAX_CALL_ATTEMPTS 와 같은 값. */
export const MAX_CALL_ATTEMPTS = 3;

export interface ClinicRequestRow {
  clinic_id: number;
  status: string;
}

export interface WorkbookListResponse {
  total_count: number;
  unmatched_count: number;
}

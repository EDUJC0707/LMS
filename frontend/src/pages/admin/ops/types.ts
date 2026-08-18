/**
 * 관리자 운영 화면이 쓰는 서버 응답 모양.
 * 전부 실제 응답을 확인해 옮긴 것이다(curl 실측) — 추측 필드 없음.
 */

// 출결 값집합·색·짧은 이름은 소비자 화면과 공유한다(src/features/attendance.ts) —
// 담임이 찍는 값과 학생·학부모가 보는 값이 갈리면 안 된다.
import type { AttendanceStatus } from "../../../features/attendance";

export type { AttendanceStatus };
export { ATTENDANCE_STATUSES } from "../../../features/attendance";

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
  /** 원번(유일). 화면에 보이는 번호. 계정 미발급이면 null */
  login_id: string | null;
  /** 지면 대조 전용 키. 중복될 수 있어 사람을 특정하지 못한다 */
  matching_key: string;
  current_class: string | null;
  enrollment_status: string;
  /** 퇴원 행. 명단에는 남지만 출결 입력 대상이 아니다(보내면 400). */
  is_withdrawn: boolean;
  attendance: AttendanceBlock | null;
}

/** 값 4종 + 미입력의 합이 total. 퇴원은 입력 대상 밖이라 total 에 들지 않는다. */
export interface AttendanceSummary {
  출석: number;
  결석: number;
  "결석(동보)": number;
  "결석(현보)": number;
  미입력: number;
  퇴원: number;
  total: number;
}

/** 출결 저장이 실제로 일으킨 파생 결과 — 사람이 자동화를 체감하는 지점. */
export interface AttendanceTriggers {
  video_grants_created: number;
  video_grants_reactivated: number;
  video_grants_revoked: number;
  counselings_created: number;
  counselings_removed: number;
  /** 결석(동보)로 확정돼 동보 지급까지 간 건수. */
  makeups_granted: number;
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
  student: {
    student_id: number;
    name: string | null;
    /** 원번(유일). 계정 미발급이면 null */
    login_id: string | null;
    /** 지면 대조 전용 키. 중복될 수 있다 */
    matching_key: string;
  };
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
  student: {
    student_id: number;
    name: string | null;
    /** 원번(유일). 계정 미발급이면 null */
    login_id: string | null;
    /** 지면 대조 전용 키. 중복될 수 있다 */
    matching_key: string;
  };
  target: string;
  status: string;
  /** 이미 수행한 통화 시도 수(0부터). 3회는 "닫아도 된다"는 신호이고 발송은 버튼이다. */
  attempts: number;
  /** 닫혔는데 결석 안내가 아직 안 나갔다 */
  awaiting_notice: boolean;
  /** 문자는 한 번만 — 보냈으면 버튼이 꺼진다 */
  notified: boolean;
  absence_date: string | null;
  created_at: string;
}

export interface CounselRecordResult {
  counsel_id: number;
  status: string;
  attempts: number;
  next_counsel_id: number | null;
  /** 더 이상 재시도 카드를 만들지 않는다 — 3회 소진 또는 강제 종결 */
  closed: boolean;
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

/** 채널톡에서 읽어 온 통화 1건 — 저장하는 것은 조교가 고른 하나뿐이다. */
export interface CounselCall {
  direction: string;
  called_at: string | null;
  connected: boolean;
  missed_reason: string | null;
  /** 통화 ID 가 없어 이것이 유일한 참조. 녹음·STT 도 이 값으로 찾는다 */
  user_chat_id: string | null;
}

/** 통화 전사 한 줄 — 자동으로 메모에 들어가지 않는다. 조교가 읽고 확정한다. */
export interface CounselTranscript {
  /** 저장된 전사 — 채널톡은 90일까지만 되돌려 주므로 우리가 갖는다 */
  transcript: string;
  /** 만료되는 서명 URL — 저장하지 않고 볼 때마다 받는다 */
  recording_url: string | null;
}

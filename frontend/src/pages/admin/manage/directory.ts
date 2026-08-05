/**
 * 학생 명부 — GET /api/admin/students (권한: 직원 공통 역할 게이트).
 *
 * 응답 행에는 **전화번호가 없다** — q 로 검색만 되고 본문에는 실리지 않는다
 * (역방향 조회 방지). 화면도 서버가 준 것만 그린다.
 *
 * 서버가 400 을 주는 조합(값집합 밖 enrollment_status)을 애초에 만들지 않는 것이
 * directoryParams 의 일이다.
 */
import type { RosterStudent } from "./types";

/** 등록 상태 값집합 — 서버와 동일. 이 밖의 값은 400 이므로 보내지 않는다. */
export const ENROLLMENT_STATUSES = ["예비등록", "등록", "퇴원"] as const;
export type EnrollmentStatus = (typeof ENROLLMENT_STATUSES)[number];

export interface DirectoryStudent {
  student_id: number;
  /** null = 계정 미발급 학생 */
  name: string | null;
  /** 원번(유일). 화면에 보이는 번호. 계정 미발급이면 null */
  login_id: string | null;
  /** 지면 대조 전용 키. 중복될 수 있어 사람을 특정하지 못한다 */
  matching_key: string;
  grade: string;
  current_class: string | null;
  enrollment_status: string;
}

export interface DirectoryPage {
  count: number;
  next: string | null;
  previous: string | null;
  results: DirectoryStudent[];
}

export interface DirectoryInput {
  q?: string;
  enrollment_status?: string;
  class_name?: string;
  page?: number;
}

/** 서버에 실제로 보낼 쿼리만 남긴다(빈 값·기본값은 아예 빼서 400·군더더기를 막는다). */
export function directoryParams(input: DirectoryInput): Record<string, string | number> {
  const params: Record<string, string | number> = {};

  const q = input.q?.trim() ?? "";
  if (q) params.q = q;

  const status = input.enrollment_status ?? "";
  if ((ENROLLMENT_STATUSES as readonly string[]).includes(status)) {
    params.enrollment_status = status;
  }

  const className = input.class_name?.trim() ?? "";
  if (className) params.class_name = className;

  if (input.page !== undefined && input.page > 1) params.page = input.page;

  return params;
}

/** 예비등록 학생 한 명 — 명부 행 + (읽을 수 있으면) 그 회차 출결. */
export interface PreRegisteredRow extends DirectoryStudent {
  /** 출결 권한이 없거나 그 회차에 기록이 없으면 null */
  attendance_status: string | null;
}

/**
 * 예비등록 명부에 출석부의 출결을 붙인다.
 * 명부(권한: 직원 공통)가 기준이고 출석부(권한: 출결입력)는 있으면 얹는다 —
 * 출결 권한이 없어도 등록 전환 목록 자체는 비지 않는다.
 */
export function mergePreRegistered(
  students: DirectoryStudent[],
  roster: RosterStudent[] | null,
): PreRegisteredRow[] {
  const byStudent = new Map<number, RosterStudent>();
  for (const row of roster ?? []) byStudent.set(row.student_id, row);

  return students.map((student) => ({
    ...student,
    attendance_status: byStudent.get(student.student_id)?.attendance?.status ?? null,
  }));
}

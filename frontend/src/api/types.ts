/**
 * /api/me 응답 타입 — 실제 서버 응답(2026-07-28 확인)에 맞춘 계약.
 *
 * 학생   { user_id, name, role:"학생",   must_change_password, student }
 * 학부모 { user_id, name, role:"학부모", must_change_password, children[] }
 * 직원   { user_id, name, role:"대표"|"관리자"|"조교", must_change_password, features[] }
 *
 * ⚠ 역할별로 없는 키는 아예 내려오지 않는다(빈 배열이 아니라 undefined).
 *   그러므로 화면은 반드시 옵셔널로 다루고, 서버가 안 준 것을 만들어내지 않는다.
 */

export type Role = "학생" | "학부모" | "대표" | "관리자" | "조교";

/** 직원 기능 키 — 권한 매트릭스(백엔드)의 값집합 그대로. */
export type Feature =
  | "결제확인"
  | "계정관리"
  | "공지작성"
  | "권한부여"
  | "문제은행관리"
  | "상담기록"
  | "성적처리"
  | "알림발송"
  | "영상지급관리"
  | "워크북업로드"
  | "출결입력"
  | "클리닉배정";

export interface MeStudent {
  student_id: number;
  enrollment_status: string; // "등록" | "예비등록" | "휴원" | "퇴원" …
  grade: string; // "고1" | "고2" …
  current_class: string | null; // "수요반" 등. 미배정이면 null
}

export interface MeChild {
  student_id: number;
  /** null = 아직 계정이 발급되지 않은 자녀 */
  name: string | null;
  grade: string;
  /**
   * "예비등록" | "등록" | "퇴원". 계정 미발급 자녀도 값이 반드시 있다.
   * 학생 블록(student.enrollment_status)과 같은 값집합이라 자녀별 메뉴를
   * 학생 화면과 똑같은 규칙으로 조립할 수 있다.
   */
  enrollment_status: string;
}

export interface Me {
  user_id: number;
  name: string;
  role: Role;
  must_change_password: boolean;
  student?: MeStudent | null; // 학생만
  children?: MeChild[]; // 학부모만
  features?: Feature[]; // 직원만
}

export const STAFF_ROLES: Role[] = ["대표", "관리자", "조교"];

export function isStaff(role: Role): boolean {
  return STAFF_ROLES.includes(role);
}

/** 역할별 홈 경로. 로그인 성공 후 여기로 보낸다. */
export function homePathFor(role: Role): string {
  if (role === "학생") return "/student";
  if (role === "학부모") return "/parent";
  return "/admin";
}

/**
 * 페이지 카탈로그 — 메뉴·인덱스가 공유하는 단일 정의.
 *
 * 접근 판정은 /api/me 응답(role·features)으로만 한다(PRD §4 상태 기반 노출
 * 메커니즘 시연). 강제는 백엔드 퍼미션이 본선이고 여기는 보조(메뉴 숨김).
 */
import { Me } from "./MeContext";

export type Access =
  | { kind: "public" }
  | { kind: "auth" } // 로그인만 필요(전 역할)
  | { kind: "role"; roles: string[] }
  | { kind: "feature"; feature: string }; // 직원 + 기능 키

export interface PageDef {
  path: string;
  label: string;
  access: Access;
  note: string;
}

export const PAGES: PageDef[] = [
  { path: "/bare/login", label: "로그인", access: { kind: "public" }, note: "로그인 3종(학생/학부모/관리자)·로그아웃" },
  { path: "/bare/password", label: "비밀번호 변경", access: { kind: "auth" }, note: "POST /api/auth/password" },
  { path: "/bare/notifications", label: "알림 내역", access: { kind: "auth" }, note: "GET /api/me/notifications" },
  { path: "/bare/boards/공지사항", label: "게시판", access: { kind: "auth" }, note: "카테고리 5종 CRUD + 댓글" },
  { path: "/bare/student/home", label: "학생 홈(캘린더)", access: { kind: "role", roles: ["학생"] }, note: "GET /api/student/home" },
  { path: "/bare/student/grades", label: "학생 성적", access: { kind: "role", roles: ["학생"] }, note: "목록·추이·성적표 상세" },
  { path: "/bare/student/clinic", label: "클리닉 신청", access: { kind: "role", roles: ["학생"] }, note: "자격·슬롯·신청/변경/취소" },
  { path: "/bare/student/makeup", label: "동보 신청(학생)", access: { kind: "role", roles: ["학생"] }, note: "POST /api/student/makeup-request" },
  { path: "/bare/student/workbook", label: "워크북(학생)", access: { kind: "role", roles: ["학생"] }, note: "GET /api/student/workbook" },
  { path: "/bare/parent/home", label: "자녀 홈(캘린더)", access: { kind: "role", roles: ["학부모"] }, note: "자녀 선택 + 결제·결석 블록" },
  { path: "/bare/parent/grades", label: "자녀 성적", access: { kind: "role", roles: ["학부모"] }, note: "GET /api/parent/grades*" },
  { path: "/bare/parent/workbook", label: "자녀 워크북", access: { kind: "role", roles: ["학부모"] }, note: "GET /api/parent/workbook" },
  { path: "/bare/parent/makeup", label: "동보 신청(학부모)", access: { kind: "role", roles: ["학부모"] }, note: "POST /api/parent/makeup-request" },
  { path: "/bare/admin/attendance", label: "출결 입력", access: { kind: "feature", feature: "출결입력" }, note: "회차 목록/명단 upsert + 트리거 피드백" },
  { path: "/bare/admin/makeup", label: "동보 관리", access: { kind: "feature", feature: "영상지급관리" }, note: "신청 목록·승인/거절·관리자 체크" },
  { path: "/bare/admin/exams", label: "시험·성적 처리", access: { kind: "feature", feature: "성적처리" }, note: "GET /api/admin/exams*" },
  { path: "/bare/admin/workbook", label: "워크북 관리", access: { kind: "feature", feature: "워크북업로드" }, note: "업로드/목록/매칭/삭제" },
  { path: "/bare/admin/clinic", label: "클리닉 관리", access: { kind: "feature", feature: "클리닉배정" }, note: "대기열·배정·출결·평가·unban" },
  { path: "/bare/admin/counseling", label: "상담 대기열", access: { kind: "feature", feature: "상담기록" }, note: "결석 상담 카드·통화 기록" },
  { path: "/bare/admin/accounts", label: "계정 일괄 발급", access: { kind: "feature", feature: "계정관리" }, note: "명단 붙여넣기 → 행별 결과·등록 전환" },
  { path: "/bare/admin/staff", label: "권한 매트릭스", access: { kind: "role", roles: ["대표"] }, note: "직원×기능 체크박스·직원 생성/비활성" },
];

export function canAccess(me: Me | null, page: PageDef): boolean {
  switch (page.access.kind) {
    case "public":
      return true;
    case "auth":
      return me !== null;
    case "role":
      return me !== null && page.access.roles.includes(me.role);
    case "feature":
      return me !== null && (me.features ?? []).includes(page.access.feature);
  }
}

export function accessLabel(access: Access): string {
  switch (access.kind) {
    case "public":
      return "누구나";
    case "auth":
      return "로그인 필요(전 역할)";
    case "role":
      return `역할: ${access.roles.join("/")}`;
    case "feature":
      return `직원 기능 키: ${access.feature}`;
  }
}

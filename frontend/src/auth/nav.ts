/**
 * 내비게이션 정의 — 메뉴는 오직 /api/me 로만 조립한다(PRD §4 상태 기반 노출).
 *
 * 규약:
 * - 자격이 없으면 "비활성"이 아니라 **목록에 없다**. 회색 처리 금지.
 * - 새 화면을 추가할 때는 여기에 항목을 추가하고 접근 조건을 명시한다.
 *   화면 안에서 다시 role 을 검사해 숨기는 방식은 쓰지 않는다(누락되기 쉬움).
 */
import { Feature, Me, Role } from "../api/types";

export interface NavItem {
  to: string;
  label: string;
  /** 하위 경로까지 활성 처리할지(예: /student/grades/12 → /student/grades 활성) */
  match?: "exact" | "prefix";
}

export interface NavGroup {
  label: string;
  items: NavItem[];
}

type Gate =
  | { kind: "always" }
  | { kind: "role"; roles: Role[] }
  | { kind: "feature"; feature: Feature }
  /** 등록 학생만(예비등록 학생에게는 성적·클리닉·워크북 자체가 없다) */
  | { kind: "enrolled" };

interface Entry extends NavItem {
  group: string;
  gate: Gate;
}

const ENTRIES: Entry[] = [
  // ── 학생 ─────────────────────────────────────────────────────────
  { group: "학습", to: "/student", label: "홈", match: "exact", gate: { kind: "role", roles: ["학생"] } },
  { group: "학습", to: "/student/grades", label: "성적", match: "prefix", gate: { kind: "enrolled" } },
  { group: "학습", to: "/student/clinic", label: "클리닉 신청", match: "prefix", gate: { kind: "enrolled" } },
  { group: "학습", to: "/student/makeup", label: "동보 신청", match: "prefix", gate: { kind: "enrolled" } },
  { group: "학습", to: "/student/workbook", label: "워크북", match: "prefix", gate: { kind: "enrolled" } },

  // ── 학부모 ───────────────────────────────────────────────────────
  { group: "자녀", to: "/parent", label: "홈", match: "exact", gate: { kind: "role", roles: ["학부모"] } },
  { group: "자녀", to: "/parent/grades", label: "성적", match: "prefix", gate: { kind: "role", roles: ["학부모"] } },
  { group: "자녀", to: "/parent/workbook", label: "워크북", match: "prefix", gate: { kind: "role", roles: ["학부모"] } },
  { group: "자녀", to: "/parent/makeup", label: "동보 신청", match: "prefix", gate: { kind: "role", roles: ["학부모"] } },

  // ── 관리자 · 운영 ────────────────────────────────────────────────
  { group: "운영", to: "/admin", label: "대시보드", match: "exact", gate: { kind: "role", roles: ["대표", "관리자", "조교"] } },
  { group: "운영", to: "/admin/attendance", label: "출결 입력", match: "prefix", gate: { kind: "feature", feature: "출결입력" } },
  { group: "운영", to: "/admin/makeup", label: "동보 관리", match: "prefix", gate: { kind: "feature", feature: "영상지급관리" } },
  { group: "운영", to: "/admin/counseling", label: "상담 대기열", match: "prefix", gate: { kind: "feature", feature: "상담기록" } },

  // ── 관리자 · 관리 ────────────────────────────────────────────────
  { group: "관리", to: "/admin/exams", label: "시험·성적", match: "prefix", gate: { kind: "feature", feature: "성적처리" } },
  { group: "관리", to: "/admin/clinic", label: "클리닉 배정", match: "prefix", gate: { kind: "feature", feature: "클리닉배정" } },
  { group: "관리", to: "/admin/workbook", label: "워크북 업로드", match: "prefix", gate: { kind: "feature", feature: "워크북업로드" } },
  { group: "관리", to: "/admin/accounts", label: "계정 발급", match: "prefix", gate: { kind: "feature", feature: "계정관리" } },
  // 권한 매트릭스는 기능 키가 아니라 **역할 게이트**다(관리자가 delta 로
  // 권한부여 키를 받아도 열리지 않는다 — 백엔드 IsCEO 와 동일 규칙).
  { group: "관리", to: "/admin/staff", label: "직원 권한", match: "prefix", gate: { kind: "role", roles: ["대표"] } },

  // ── 공통 ─────────────────────────────────────────────────────────
  { group: "공통", to: "/boards/공지사항", label: "게시판", match: "prefix", gate: { kind: "always" } },
  { group: "공통", to: "/notifications", label: "알림", match: "prefix", gate: { kind: "always" } },
];

function allowed(me: Me, gate: Gate): boolean {
  switch (gate.kind) {
    case "always":
      return true;
    case "role":
      return gate.roles.includes(me.role);
    case "feature":
      return (me.features ?? []).includes(gate.feature);
    case "enrolled":
      return me.role === "학생" && me.student?.enrollment_status === "등록";
  }
}

/** 게시판 경로는 카테고리를 갖는다 — prefix 매칭용 베이스. */
export const BOARD_BASE = "/boards";

/** 현재 사용자에게 보여줄 내비게이션. 자격 없는 항목은 아예 빠진다. */
export function navFor(me: Me): NavGroup[] {
  const groups = new Map<string, NavItem[]>();
  for (const entry of ENTRIES) {
    if (!allowed(me, entry.gate)) continue;
    const list = groups.get(entry.group) ?? [];
    list.push({ to: entry.to, label: entry.label, match: entry.match });
    groups.set(entry.group, list);
  }
  return [...groups].map(([label, items]) => ({ label, items }));
}

/** 사이드레일 라벨(역할별 셸 제목). */
export function shellTitleFor(me: Me): string {
  if (me.role === "학생") return "학생";
  if (me.role === "학부모") return "학부모";
  return `${me.role} 콘솔`;
}

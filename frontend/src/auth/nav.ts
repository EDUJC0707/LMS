/**
 * 내비게이션 정의 — 메뉴는 오직 /api/me 로만 조립한다(PRD §4 상태 기반 노출).
 *
 * 이 파일은 **화면 이름의 단일 준거**다. 좌측 레일의 링크 라벨과 상단바에 뜨는
 * 페이지 이름이 같은 문자열·같은 아이콘을 여기서 가져간다(두 곳이 어긋날 수 없다).
 *
 * 규약:
 * - 자격이 없으면 "비활성"이 아니라 **목록에 없다**. 회색 처리 금지.
 * - 새 화면을 추가할 때는 여기에 항목을 추가하고 접근 조건·아이콘을 명시한다.
 *   화면 안에서 다시 role 을 검사해 숨기는 방식은 쓰지 않는다(누락되기 쉬움).
 * - **화면은 자기 제목을 그리지 않는다.** 제목은 상단바가 pageFor() 로 그린다.
 */
import { Feature, Me, Role } from "../api/types";
import type { PageIconName } from "../components/PageIcon";

export interface NavItem {
  to: string;
  label: string;
  /** 레일 항목과 상단바가 함께 쓰는 기호. components/PageIcon.tsx 에 도형이 있다. */
  icon: PageIconName;
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
  /**
   * 이 항목이 담당하는 경로 접두사. 링크 주소(`to`)와 담당 범위가 다를 때만 쓴다
   * (게시판: 링크는 /boards/공지사항 이지만 /boards/* 전체가 이 화면이다).
   */
  base?: string;
}

const ENTRIES: Entry[] = [
  // ── 학생 ─────────────────────────────────────────────────────────
  { group: "학습", to: "/student", label: "홈", icon: "calendar", match: "exact", gate: { kind: "role", roles: ["학생"] } },
  { group: "학습", to: "/student/grades", label: "성적", icon: "chart", match: "prefix", gate: { kind: "enrolled" } },
  { group: "학습", to: "/student/clinic", label: "클리닉 신청", icon: "video", match: "prefix", gate: { kind: "enrolled" } },
  { group: "학습", to: "/student/videos", label: "복습영상", icon: "video", match: "prefix", gate: { kind: "enrolled" } },
  { group: "학습", to: "/student/makeup", label: "동보 신청", icon: "play", match: "prefix", gate: { kind: "enrolled" } },
  { group: "학습", to: "/student/workbook", label: "워크북", icon: "notebook", match: "prefix", gate: { kind: "enrolled" } },

  // ── 학부모 ───────────────────────────────────────────────────────
  { group: "자녀", to: "/parent", label: "홈", icon: "calendar", match: "exact", gate: { kind: "role", roles: ["학부모"] } },
  { group: "자녀", to: "/parent/grades", label: "성적", icon: "chart", match: "prefix", gate: { kind: "role", roles: ["학부모"] } },
  { group: "자녀", to: "/parent/workbook", label: "워크북", icon: "notebook", match: "prefix", gate: { kind: "role", roles: ["학부모"] } },
  { group: "자녀", to: "/parent/makeup", label: "동보 신청", icon: "play", match: "prefix", gate: { kind: "role", roles: ["학부모"] } },

  // ── 관리자 · 운영 ────────────────────────────────────────────────
  { group: "운영", to: "/admin", label: "대시보드", icon: "dashboard", match: "exact", gate: { kind: "role", roles: ["대표", "관리자", "조교"] } },
  { group: "운영", to: "/admin/attendance", label: "출결 입력", icon: "checklist", match: "prefix", gate: { kind: "feature", feature: "출결입력" } },
  { group: "운영", to: "/admin/makeup", label: "동보 관리", icon: "play", match: "prefix", gate: { kind: "feature", feature: "영상지급관리" } },
  { group: "운영", to: "/admin/counseling", label: "상담 대기열", icon: "counsel", match: "prefix", gate: { kind: "feature", feature: "상담기록" } },

  // ── 관리자 · 관리 ────────────────────────────────────────────────
  { group: "관리", to: "/admin/exams", label: "시험·성적", icon: "exam", match: "prefix", gate: { kind: "feature", feature: "성적처리" } },
  { group: "관리", to: "/admin/clinic", label: "클리닉 배정", icon: "video", match: "prefix", gate: { kind: "feature", feature: "클리닉배정" } },
  { group: "관리", to: "/admin/workbook", label: "워크북 업로드", icon: "upload", match: "prefix", gate: { kind: "feature", feature: "워크북업로드" } },
  { group: "관리", to: "/admin/accounts", label: "계정 발급", icon: "key", match: "prefix", gate: { kind: "feature", feature: "계정관리" } },
  // 권한 매트릭스는 기능 키가 아니라 **역할 게이트**다(관리자가 delta 로
  // 권한부여 키를 받아도 열리지 않는다 — 백엔드 IsCEO 와 동일 규칙).
  { group: "관리", to: "/admin/staff", label: "직원 권한", icon: "shield", match: "prefix", gate: { kind: "role", roles: ["대표"] } },

  // ── 공통 ─────────────────────────────────────────────────────────
  { group: "공통", to: "/boards/공지사항", base: "/boards", label: "게시판", icon: "board", match: "prefix", gate: { kind: "always" } },
  { group: "공통", to: "/notifications", label: "알림", icon: "bell", match: "prefix", gate: { kind: "always" } },
];

/**
 * 레일 맨 아래 한 칸. 그룹 목록과 섞지 않는다(기능이 아니라 계정 설정이라서).
 * 상단바도 이 항목으로 /password 의 페이지 이름을 찾는다.
 */
const FOOT_ENTRY: Entry = {
  group: "계정",
  to: "/password",
  label: "비밀번호 변경",
  icon: "lock",
  match: "prefix",
  gate: { kind: "always" },
};

export const RAIL_FOOT: NavItem = {
  to: FOOT_ENTRY.to,
  label: FOOT_ENTRY.label,
  icon: FOOT_ENTRY.icon,
  match: FOOT_ENTRY.match,
};

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
    list.push({ to: entry.to, label: entry.label, icon: entry.icon, match: entry.match });
    groups.set(entry.group, list);
  }
  return [...groups].map(([label, items]) => ({ label, items }));
}

function covers(entry: Entry, pathname: string): boolean {
  const base = entry.base ?? entry.to;
  return entry.match === "prefix"
    ? pathname === base || pathname.startsWith(`${base}/`)
    : pathname === base;
}

/**
 * 지금 보고 있는 화면 — 상단바가 그릴 이름·아이콘.
 *
 * 자격 게이트는 보지 않는다(라우트 가드가 이미 막았다). 경로만으로 고르고,
 * 겹치면 더 긴 경로가 이긴다(/student 보다 /student/grades 가 우선).
 * 어느 항목도 담당하지 않는 경로(404)면 null — 그때만 화면이 자기 제목을 갖는다.
 */
export function pageFor(pathname: string): NavItem | null {
  let best: Entry | null = null;
  for (const entry of [...ENTRIES, FOOT_ENTRY]) {
    if (!covers(entry, pathname)) continue;
    const length = (entry.base ?? entry.to).length;
    if (!best || length > (best.base ?? best.to).length) best = entry;
  }
  if (!best) return null;
  return { to: best.to, label: best.label, icon: best.icon, match: best.match };
}

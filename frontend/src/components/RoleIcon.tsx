/**
 * 역할 아이콘 — 계정 칩의 이니셜 원("김")을 대체한다.
 *
 * 이니셜은 바로 옆에 이름이 그대로 적혀 있어 정보가 중복이고, 성씨 한 글자만
 * 크게 떠서 읽는 사람이 얻는 게 없다(2026-07-28 사용자 지적).
 *
 * 선 아이콘 세 종. 색은 currentColor 를 따르므로 칩 색만 바꾸면 같이 따라온다.
 * 획 굵기·모서리는 시스템의 기하학적 결에 맞춘다.
 *   학생   펼친 책 — 공부하는 사람
 *   학부모 어른과 아이 — 자녀를 지켜보는 계정
 *   직원   클립보드 — 기록하고 처리하는 사람(대표·관리자·조교 공통)
 */
import { Role } from "../api/types";

const COMMON = {
  width: 20,
  height: 20,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.7,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
  focusable: "false" as const,
};

function StudentIcon() {
  // 연필. **다른 아이콘보다 의도적으로 작게 그린다** — 대각선 도형은 상자의
  // 모서리에서 모서리까지 뻗어 같은 크기여도 더 크게 보인다(광학 보정).
  // 세로·가로 위주인 학부모·직원 아이콘과 무게를 맞춘 값이다. 키우지 말 것.
  return (
    <svg {...COMMON}>
      <path d="M15 6 18 9" />
      <path d="M16.3 4.7a1.9 1.9 0 0 1 2.6 2.6L9.2 17l-3.7 1.3 1.3-3.7L16.3 4.7Z" />
    </svg>
  );
}

function ParentIcon() {
  return (
    <svg {...COMMON}>
      <circle cx="9" cy="7.4" r="3.1" />
      <path d="M3.6 19.4c0-2.7 2.4-4.6 5.4-4.6s5.4 1.9 5.4 4.6" />
      <circle cx="17.4" cy="11.6" r="2.1" />
      <path d="M14.2 19.4c0-1.9 1.4-3.2 3.2-3.2s3.2 1.3 3.2 3.2" />
    </svg>
  );
}

function StaffIcon() {
  return (
    <svg {...COMMON}>
      <path d="M8.4 4.8H6.2a1.6 1.6 0 0 0-1.6 1.6v12.4a1.6 1.6 0 0 0 1.6 1.6h11.6a1.6 1.6 0 0 0 1.6-1.6V6.4a1.6 1.6 0 0 0-1.6-1.6h-2.2" />
      <rect x="8.4" y="3" width="7.2" height="3.6" rx="1.2" />
      <path d="M8.6 12.2h6.8M8.6 15.8h4.4" />
    </svg>
  );
}

export function RoleIcon({ role }: { role: Role }) {
  if (role === "학생") return <StudentIcon />;
  if (role === "학부모") return <ParentIcon />;
  return <StaffIcon />;
}

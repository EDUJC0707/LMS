/**
 * 페이지 아이콘 — 상단바의 현재 페이지 표시와 좌측 레일 항목이 **같은 기호**를 쓴다.
 *
 * 아이콘 이름은 `auth/nav.ts` 의 항목에 붙어 있다(단일 준거). 화면을 추가할 때는
 * 여기에 도형을 그리고 nav 항목에 이름을 적는다 — 두 곳이 어긋날 수 없게.
 *
 * 결은 RoleIcon 과 동일하다: viewBox 24, stroke 1.7, currentColor, 둥근 끝.
 * 색을 직접 넣지 않는다 — 쓰는 쪽에서 color 로 정한다.
 * 도형은 대략 지름 17~18 단위 안에 들어오게 그린다(광학 크기를 맞추기 위함).
 */
export type PageIconName =
  | "calendar" // 홈 — 이번 달 일정
  | "chart" // 성적 — 점수 추이
  | "video" // 클리닉 — 화상
  | "play" // 동보 — 복습영상 재생
  | "notebook" // 워크북
  | "upload" // 워크북 업로드
  | "board" // 게시판
  | "bell" // 알림
  | "dashboard" // 관리자 대시보드
  | "checklist" // 출결 입력
  | "counsel" // 상담 대기열
  | "exam" // 시험·성적
  | "key" // 계정 발급
  | "shield" // 직원 권한
  | "lock"; // 비밀번호 변경

const SHAPES: Record<PageIconName, JSX.Element> = {
  calendar: (
    <>
      <rect x="3.4" y="5.2" width="17.2" height="15.4" rx="2.2" />
      <path d="M3.4 10.2h17.2" />
      <path d="M8.2 3.4v3.6M15.8 3.4v3.6" />
      <path d="M7.8 14.4h2.8" />
    </>
  ),
  chart: (
    // 막대가 짧으면 다른 아이콘보다 작아 보인다 — 상자 높이를 거의 다 쓴다.
    <>
      <path d="M3.8 20.4h16.4" />
      <path d="M7.4 20.4v-6.6M12 20.4v-10.6M16.6 20.4v-14.6" />
    </>
  ),
  video: (
    <>
      <rect x="2.8" y="6.6" width="13.2" height="10.8" rx="2.4" />
      <path d="M16 11.2 20.2 8.6a0.7 0.7 0 0 1 1 .6v5.6a0.7 0.7 0 0 1-1 .6L16 12.8Z" />
    </>
  ),
  play: (
    <>
      <circle cx="12" cy="12" r="8.6" />
      <path d="M10.2 8.8 16.2 12l-6 3.2Z" />
    </>
  ),
  notebook: (
    <>
      <path d="M6.6 3.6h11.2a1.8 1.8 0 0 1 1.8 1.8v13.2a1.8 1.8 0 0 1-1.8 1.8H6.6a2 2 0 0 1-2-2V5.6a2 2 0 0 1 2-2Z" />
      <path d="M8.4 3.6v16.8" />
      <path d="M11.4 8.4h5M11.4 12h5M11.4 15.6h3" />
    </>
  ),
  upload: (
    <>
      <path d="M12 15.2V4.4" />
      <path d="m8 8.4 4-4 4 4" />
      <path d="M4.6 15.6v2.8a2 2 0 0 0 2 2h10.8a2 2 0 0 0 2-2v-2.8" />
    </>
  ),
  board: (
    <>
      <path d="M20.4 12.4c0 3.8-3.8 6.9-8.4 6.9-1 0-2-.15-2.9-.42L4.4 20.6l1.4-3.6C4.4 15.8 3.6 14.2 3.6 12.4c0-3.8 3.8-6.9 8.4-6.9s8.4 3.1 8.4 6.9Z" />
      <path d="M8.8 10.6h6.4M8.8 13.8h4" />
    </>
  ),
  bell: (
    <>
      <path d="M18 10.6a6 6 0 1 0-12 0c0 4.2-1.6 5.6-1.6 5.6h15.2S18 14.8 18 10.6Z" />
      <path d="M10.2 19.4a2.1 2.1 0 0 0 3.6 0" />
    </>
  ),
  dashboard: (
    <>
      <rect x="3.6" y="3.6" width="7.4" height="7.4" rx="1.6" />
      <rect x="13" y="3.6" width="7.4" height="4.6" rx="1.6" />
      <rect x="3.6" y="13" width="7.4" height="7.4" rx="1.6" />
      <rect x="13" y="10.2" width="7.4" height="10.4" rx="1.6" />
    </>
  ),
  checklist: (
    <>
      <path d="m3.6 8.2 1.9 1.9 3.4-3.6" />
      <path d="m3.6 16.4 1.9 1.9 3.4-3.6" />
      <path d="M12 8.4h8.4M12 16.6h8.4" />
    </>
  ),
  counsel: (
    <>
      {/* 게시판(단독 말풍선)과 헷갈리지 않게 사람을 앞에 세운다 */}
      <circle cx="7.6" cy="7.6" r="3.2" />
      <path d="M2.4 19.4c0-3 2.3-5.2 5.2-5.2.8 0 1.6.15 2.3.44" />
      <path d="M13.6 9.4h6a1.7 1.7 0 0 1 1.7 1.7v4.2a1.7 1.7 0 0 1-1.7 1.7h-2.2l-2.6 2.2v-2.2h-1.2a1.7 1.7 0 0 1-1.7-1.7v-4.2a1.7 1.7 0 0 1 1.7-1.7Z" />
    </>
  ),
  exam: (
    <>
      <path d="M13.8 3.4H7a2 2 0 0 0-2 2v13.2a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8.6Z" />
      <path d="M13.8 3.4v4.2a1 1 0 0 0 1 1H19" />
      <path d="m8.8 14.6 2 2 4-4.4" />
    </>
  ),
  key: (
    <>
      <circle cx="8.2" cy="15.8" r="4.4" />
      <path d="M11.4 12.6 19.4 4.6" />
      <path d="m16.4 7.6 2.4 2.4M18.8 5.2l2.4 2.4" />
    </>
  ),
  shield: (
    <>
      <path d="m12 3.2 7.2 2.8v5.6c0 4.4-3 7.8-7.2 9.2-4.2-1.4-7.2-4.8-7.2-9.2V6L12 3.2Z" />
      <path d="m9.2 12.2 2 2 3.6-4" />
    </>
  ),
  lock: (
    <>
      <rect x="4.6" y="10.4" width="14.8" height="10" rx="2.2" />
      <path d="M8.2 10.4V7.8a3.8 3.8 0 0 1 7.6 0v2.6" />
    </>
  ),
};

/** 장식용이다 — 옆에 항상 페이지 이름이 같이 있으므로 스크린리더에서 숨긴다. */
/*
 * 3D 모티프(`local/assets/motifs_accent`)를 이 자리에 넣어 봤다가 되돌렸다
 * (2026-07-28). 20~27px 에서는 렌더가 뭉개지고, 무엇보다 이 자리는 "지금 어느
 * 화면인가"를 가리키는 기능 표식이라 손으로 그린 선 아이콘이 맞다.
 * 모티프는 크기가 나오고 내용과 연결되는 자리(주차별 단원·랜딩)에서 쓴다.
 */
export function PageIcon({
  name,
  size = 20,
  className,
}: {
  name: PageIconName;
  size?: number;
  className?: string;
}) {
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.7}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden={true}
      focusable="false"
    >
      {SHAPES[name]}
    </svg>
  );
}

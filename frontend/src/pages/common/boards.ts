/**
 * 게시판 공용 계약 — 카테고리 값집합·응답 타입·작성 권한·날짜 표기.
 *
 * 카테고리 값은 backend/apps/boards/models.py 의 Post.Category 그대로다
 * (URL 세그먼트 = 모델 값). 밖의 값은 서버가 404 를 준다.
 *
 * 작성 권한은 backend/apps/boards/board.py 의 can_write 매트릭스를 그대로
 * 옮긴 것이다 — 강제는 서버가 하고, 여기서는 "자격 없는 기능은 화면에
 * 아예 없다"(PRD §4)를 지키기 위해 버튼 노출만 판단한다.
 */
import { Me } from "../../api";

export const BOARD_CATEGORIES = ["공지사항", "질답", "정오표", "자유게시판", "이벤트굿즈"] as const;

export type BoardCategory = (typeof BOARD_CATEGORIES)[number];

export function isBoardCategory(value: string): value is BoardCategory {
  return (BOARD_CATEGORIES as readonly string[]).includes(value);
}

/** DRF PAGE_SIZE (backend/config/settings/base.py) — 페이지 수 계산용. */
export const API_PAGE_SIZE = 20;

export interface CourseWeekRef {
  week_id: number;
  week_no: number;
  course_name: string;
}

export interface PostRow {
  post_id: number;
  /** 비밀글이면 타인에게는 "비밀글입니다"로 내려온다. */
  title: string;
  /** 비밀글이면 타인에게는 null. */
  author_name: string | null;
  is_secret: boolean;
  is_published: boolean;
  comment_count: number;
  course_week: CourseWeekRef | null;
  created_at: string;
  updated_at: string | null;
  is_mine: boolean;
}

export interface CommentRow {
  comment_id: number;
  author_name: string;
  author_role: string;
  body: string;
  created_at: string;
  is_mine: boolean;
}

export interface PostDetail {
  post_id: number;
  category: BoardCategory;
  title: string;
  body: string;
  author_name: string;
  is_secret: boolean;
  is_published: boolean;
  course_week: CourseWeekRef | null;
  created_at: string;
  updated_at: string | null;
  is_mine: boolean;
  comments: CommentRow[];
}

export interface Paged<Row> {
  count: number;
  next: string | null;
  previous: string | null;
  results: Row[];
}

/** 글이 하나도 없을 때의 문구. */
export const BOARD_EMPTY: Record<BoardCategory, string> = {
  공지사항: "아직 올라온 공지가 없습니다.",
  질답: "아직 올라온 질문이 없습니다.",
  정오표: "아직 바로잡은 내용이 없습니다.",
  자유게시판: "아직 올라온 글이 없습니다.",
  이벤트굿즈: "아직 진행 중인 이벤트가 없습니다.",
};

/** 글쓰기 버튼 라벨(카테고리마다 하는 일이 다르다). */
export const BOARD_WRITE_LABEL: Record<BoardCategory, string> = {
  공지사항: "공지 쓰기",
  질답: "질문하기",
  정오표: "정오표 쓰기",
  자유게시판: "글쓰기",
  이벤트굿즈: "글쓰기",
};

export const BOARD_TITLE_LABEL: Record<BoardCategory, string> = {
  공지사항: "제목",
  질답: "질문 제목",
  정오표: "제목",
  자유게시판: "제목",
  이벤트굿즈: "제목",
};

export const BOARD_BODY_LABEL: Record<BoardCategory, string> = {
  공지사항: "내용",
  질답: "질문 내용",
  정오표: "내용",
  자유게시판: "내용",
  이벤트굿즈: "내용",
};

/**
 * 작성 권한(backend board.can_write 와 동일 규칙).
 * 공지사항·정오표·이벤트굿즈 = 기능 키 `공지작성`(대표는 전권으로 이미 보유),
 * 질답 = 학생·학부모, 자유게시판 = 대표.
 */
export function canWriteBoard(category: BoardCategory, me: Me | null): boolean {
  if (!me) return false;
  if (category === "자유게시판") return me.role === "대표";
  if (category === "질답") return me.role === "학생" || me.role === "학부모";
  return (me.features ?? []).includes("공지작성");
}

/** 직원 운영 삭제(타인 글·댓글) — backend board.can_moderate 와 동일. */
export function canModerateBoard(me: Me | null): boolean {
  return !!me && (me.features ?? []).includes("공지작성");
}

/** 비밀글 옵션은 질답에서만 제공된다(서버도 다른 카테고리는 400). */
export function allowsSecret(category: BoardCategory): boolean {
  return category === "질답";
}

/** 목록에서 마스킹된 비밀글인지 — 원제목·작성자가 가려져 상세도 열 수 없다. */
export function isMasked(post: PostRow): boolean {
  return post.is_secret && post.author_name === null;
}

// ── 날짜 표기 ─────────────────────────────────────────────────────────

function parse(value: string | null | undefined): Date | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

const dayInYear = new Intl.DateTimeFormat("ko-KR", { month: "long", day: "numeric" });
const dayWithYear = new Intl.DateTimeFormat("ko-KR", {
  year: "numeric",
  month: "long",
  day: "numeric",
});
const weekdayOnly = new Intl.DateTimeFormat("ko-KR", { weekday: "short" });
const stamp = new Intl.DateTimeFormat("ko-KR", {
  year: "numeric",
  month: "long",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
});
const timeOnly = new Intl.DateTimeFormat("ko-KR", { hour: "numeric", minute: "2-digit" });

/** 목록용 — 올해면 "7월 22일", 지난해면 "2025년 12월 3일". */
export function formatDay(value: string | null | undefined): string {
  const date = parse(value);
  if (!date) return "";
  const sameYear = date.getFullYear() === new Date().getFullYear();
  return (sameYear ? dayInYear : dayWithYear).format(date);
}

/** 상세용 — "2026년 7월 22일 오후 9:47". */
export function formatStamp(value: string | null | undefined): string {
  const date = parse(value);
  return date ? stamp.format(date) : "";
}

/** 시각만 — "오후 9:47". */
export function formatTime(value: string | null | undefined): string {
  const date = parse(value);
  return date ? timeOnly.format(date) : "";
}

/** 날짜 묶음 머리글 — "오늘" / "어제" / "7월 22일 (화)". */
export function formatDayGroup(value: string | null | undefined): string {
  const date = parse(value);
  if (!date) return "날짜를 알 수 없는 알림";
  const midnight = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const gap = Math.round((midnight(new Date()) - midnight(date)) / 86_400_000);
  if (gap === 0) return "오늘";
  if (gap === 1) return "어제";
  return `${formatDay(value)} (${weekdayOnly.format(date)})`;
}

/** 같은 날짜끼리 묶는다(서버가 이미 최신순이라 연속 구간만 본다). */
export function groupByDay<Row>(
  rows: Row[],
  at: (row: Row) => string,
): { key: string; label: string; rows: Row[] }[] {
  const groups: { key: string; label: string; rows: Row[] }[] = [];
  for (const row of rows) {
    const label = formatDayGroup(at(row));
    const last = groups[groups.length - 1];
    if (last && last.label === label) last.rows.push(row);
    else groups.push({ key: `${label}-${groups.length}`, label, rows: [row] });
  }
  return groups;
}

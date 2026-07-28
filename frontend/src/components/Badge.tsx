import { ReactNode } from "react";

export type BadgeTone = "neutral" | "accent" | "success" | "warning" | "danger" | "outline";

export interface BadgeProps {
  /** 상태색은 의미 전용이다 — success=완료/출석/승인, warning=보류/지각,
   *  danger=결석/거절/삭제, accent=진행중·강조, neutral=중립 라벨. */
  tone?: BadgeTone;
  children: ReactNode;
  className?: string;
}

export function Badge({ tone = "neutral", children, className = "" }: BadgeProps) {
  return <span className={`ui-badge ui-badge--${tone} ${className}`.trim()}>{children}</span>;
}

/** 출결·신청 상태 문자열을 톤에 매핑한다. 모르는 값은 중립. */
const TONE_BY_STATUS: Record<string, BadgeTone> = {
  출석: "success",
  승인: "success",
  완료: "success",
  등록: "success",
  배정: "success",
  승인배정: "success", // 클리닉 신청 상태(ClinicRequest.Status.APPROVED) 원문
  지각: "warning",
  대기: "warning",
  보류: "warning",
  신청: "warning",
  예비등록: "warning",
  결석: "danger",
  거절: "danger",
  취소: "danger",
  퇴원: "danger",
  휴원: "neutral",
};

/** 서버가 내려준 상태 문자열을 그대로 뱃지로. */
export function StatusBadge({ status }: { status: string }) {
  return <Badge tone={TONE_BY_STATUS[status] ?? "neutral"}>{status}</Badge>;
}

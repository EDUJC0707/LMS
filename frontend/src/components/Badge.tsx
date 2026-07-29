import { ReactNode } from "react";

export type BadgeTone = "neutral" | "accent" | "success" | "warning" | "danger" | "outline";

export interface BadgeProps {
  /** 상태색은 의미 전용이다 — success=완료/출석/승인, warning=보류/동보,
   *  danger=결석/거절/삭제, accent=진행중·강조·현보, neutral=중립 라벨. */
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
  대기: "warning",
  보류: "warning",
  신청: "warning",
  예비등록: "warning",
  // 출결 값집합 4종(2026-07-29) — 결석 셋은 보강 여부로 갈린다.
  // 손이 더 가야 하는 순서대로 색을 준다: 보강 미정만 danger.
  "결석(동보)": "warning",
  "결석(현보)": "accent",
  결석: "danger",
  거절: "danger",
  취소: "danger",
  퇴원: "danger",
  휴원: "neutral",
};

/** 서버가 내려준 상태 문자열을 그대로 뱃지로.
 *
 *  `label` 은 **좁은 칸에서만** 쓴다(캘린더 한 칸 등) — 색은 원래 상태로 잡되
 *  글자만 짧게. 뜻이 흐려지지 않도록 같은 화면에 원문 범례를 함께 둔다. */
export function StatusBadge({ status, label }: { status: string; label?: string }) {
  return <Badge tone={TONE_BY_STATUS[status] ?? "neutral"}>{label ?? status}</Badge>;
}

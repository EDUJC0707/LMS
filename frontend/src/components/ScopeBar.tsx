import { ReactNode } from "react";

/**
 * 본문 첫 줄의 **범위 스위처** — 화면 전체가 무엇을 보고 있는지 바꾸는 컨트롤만 온다.
 * (자녀 선택 · 대상 시험 선택 · 기간 선택처럼 아래 카드 전부를 갈아끼우는 것)
 *
 * 옛 PageHeader 의 `actions` 자리를 대신하지만 제목·설명은 받지 않는다 —
 * 제목은 상단바(AppShell), 나머지 액션은 그 데이터를 가진 Card 의 actions 로 간다.
 * 카드 하나만 바꾸는 컨트롤(달 이동 등)을 여기 올리지 말 것.
 */
export function ScopeBar({ children }: { children: ReactNode }) {
  return <div className="ui-scopebar">{children}</div>;
}

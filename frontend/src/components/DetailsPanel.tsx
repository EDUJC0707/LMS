import { ReactNode } from "react";

export interface DetailsPanelProps {
  summary: ReactNode;
  /** 요약줄 오른쪽 보조 텍스트(건수·상태). */
  aside?: ReactNode;
  /** 처음부터 펼친 상태로. */
  defaultOpen?: boolean;
  children: ReactNode;
}

/**
 * 접이식 패널. 네이티브 <details> 라 키보드·스크린리더가 그냥 동작한다.
 * 터치 환경이므로 "hover 하면 펼쳐짐" 같은 건 만들지 않는다 — 탭해서 연다.
 */
export function DetailsPanel({ summary, aside, defaultOpen = false, children }: DetailsPanelProps) {
  return (
    <details className="ui-details" open={defaultOpen}>
      <summary className="ui-details__summary">
        <svg
          className="ui-details__chevron"
          width="16"
          height="16"
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          aria-hidden="true"
        >
          <path d="M6 3.5l4.5 4.5L6 12.5" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        {summary}
        {aside && <span className="ui-details__aside">{aside}</span>}
      </summary>
      <div className="ui-details__body">{children}</div>
    </details>
  );
}

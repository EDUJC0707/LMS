import { ReactNode } from "react";

import { Button } from "./Button";

export interface EmptyStateProps {
  /** 왜 비어 있는지 한 줄. "데이터 없음" 같은 말은 쓰지 않는다. */
  title: string;
  description?: ReactNode;
  /** 비어 있는 상태를 벗어나는 행동(신청하기·업로드 등). */
  action?: ReactNode;
}

export function EmptyState({ title, description, action }: EmptyStateProps) {
  return (
    <div className="ui-state">
      <span className="ui-state__mark" aria-hidden="true">
        <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor">
          <rect x="3.5" y="4.5" width="13" height="11" rx="2" strokeWidth="1.4" />
          <path d="M3.5 8.5h13" strokeWidth="1.4" />
        </svg>
      </span>
      <p className="ui-state__title">{title}</p>
      {description && <p className="ui-state__desc">{description}</p>}
      {action && <div className="ui-state__action">{action}</div>}
    </div>
  );
}

export interface ErrorStateProps {
  title?: string;
  /** 서버 detail 을 그대로 넣는다(toMessage 결과). */
  description?: ReactNode;
  /** 있으면 "다시 시도" 버튼이 붙는다. */
  onRetry?: () => void;
}

export function ErrorState({
  title = "화면을 불러오지 못했습니다",
  description,
  onRetry,
}: ErrorStateProps) {
  return (
    <div className="ui-state ui-state--error" role="alert">
      <span className="ui-state__mark" aria-hidden="true">
        <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor">
          <circle cx="10" cy="10" r="7" strokeWidth="1.4" />
          <path d="M10 6.5v4.2" strokeWidth="1.6" strokeLinecap="round" />
          <circle cx="10" cy="13.6" r="0.9" fill="currentColor" stroke="none" />
        </svg>
      </span>
      <p className="ui-state__title">{title}</p>
      {description && <p className="ui-state__desc">{description}</p>}
      {onRetry && (
        <div className="ui-state__action">
          <Button onClick={onRetry}>다시 시도</Button>
        </div>
      )}
    </div>
  );
}

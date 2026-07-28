import { ReactNode } from "react";

export type AlertTone = "info" | "success" | "warning" | "danger";

export interface AlertProps {
  tone?: AlertTone;
  children: ReactNode;
  /** 있으면 닫기 버튼이 붙는다. */
  onClose?: () => void;
  className?: string;
}

const MARK: Record<AlertTone, string> = {
  info: "i",
  success: "✓",
  warning: "!",
  danger: "!",
};

/**
 * 인라인 알림. 폼 바로 위·아래에 붙여 쓴다.
 * 성공은 조용히 넘어가는 게 기본이고, 결과가 화면에 안 보일 때만 success 를 쓴다.
 */
export function Alert({ tone = "info", children, onClose, className = "" }: AlertProps) {
  return (
    <div
      className={`ui-alert ui-alert--${tone} ${className}`.trim()}
      role={tone === "danger" ? "alert" : "status"}
    >
      <span className="ui-alert__mark" aria-hidden="true">
        {MARK[tone]}
      </span>
      <span className="ui-alert__text">{children}</span>
      {onClose && (
        <button type="button" className="ui-alert__close" onClick={onClose} aria-label="닫기">
          ✕
        </button>
      )}
    </div>
  );
}

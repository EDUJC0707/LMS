export interface SpinnerProps {
  size?: "sm" | "md" | "lg";
  className?: string;
  /** 화면 낭독용 라벨. 버튼 안처럼 문맥이 이미 있으면 생략한다. */
  label?: string;
}

export function Spinner({ size = "md", className = "", label }: SpinnerProps) {
  return (
    <span
      className={`ui-spinner ui-spinner--${size} ${className}`.trim()}
      role={label ? "status" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
    />
  );
}

/** 페이지·패널 단위 로딩. 스피너가 50ms 만 번쩍이지 않게 문구를 함께 둔다. */
export function Loading({ label = "불러오는 중…" }: { label?: string }) {
  return (
    <div className="ui-loading" role="status" aria-live="polite">
      <Spinner size="lg" />
      <span>{label}</span>
    </div>
  );
}

import { ReactNode } from "react";

export interface CardProps {
  /** 제목이 있으면 헤더 줄이 생긴다. 없으면 본문만. */
  title?: ReactNode;
  /** 헤더 오른쪽 보조 텍스트(건수·기준일 등). */
  aside?: ReactNode;
  /** 헤더 오른쪽 액션 버튼들. aside 와 함께 쓸 수 있다. */
  actions?: ReactNode;
  /** "md"=기본 24px · "sm"=16px · "none"=표/리스트를 가장자리까지 붙일 때 */
  padding?: "md" | "sm" | "none";
  /** 그림자 없이 선만 — 카드가 여러 개 늘어설 때 시각 소음을 줄인다. */
  flat?: boolean;
  className?: string;
  children: ReactNode;
}

/** 표면 한 겹. 카드 안에 카드를 넣지 말 것(중첩 금지). */
export function Card({
  title,
  aside,
  actions,
  padding = "md",
  flat = false,
  className = "",
  children,
}: CardProps) {
  const bodyClass =
    padding === "none"
      ? "ui-card__body ui-card__body--flush"
      : padding === "sm"
        ? "ui-card__body ui-card__body--tight"
        : "ui-card__body";

  return (
    <section className={`ui-card ${flat ? "ui-card--flat" : ""} ${className}`.trim()}>
      {(title || aside || actions) && (
        <header className="ui-card__head">
          {title && <h2 className="ui-card__title">{title}</h2>}
          {aside && <span className="ui-card__aside">{aside}</span>}
          {actions && (
            <div className="ui-row" style={{ marginLeft: aside ? undefined : "auto" }}>
              {actions}
            </div>
          )}
        </header>
      )}
      <div className={bodyClass}>{children}</div>
    </section>
  );
}

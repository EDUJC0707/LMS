import { ReactNode } from "react";

export interface PageHeaderProps {
  /** 페이지 제목. 화면당 h1 은 이것 하나뿐이다. */
  title: string;
  /** 제목 옆 메타 — 이름·날짜·회차 같은 **데이터**만. 화면 설명을 넣지 않는다(CLAUDE.md §8). */
  description?: ReactNode;
  /** 오른쪽 액션 버튼들. */
  actions?: ReactNode;
}

/** 모든 페이지의 첫 요소. 제목 아래 하나의 구분선으로 본문과 나뉜다. */
export function PageHeader({ title, description, actions }: PageHeaderProps) {
  return (
    <header className="ui-pagehead">
      <div className="ui-pagehead__text">
        <h1 className="ui-pagehead__title">{title}</h1>
        {description && <p className="ui-pagehead__desc">{description}</p>}
      </div>
      {actions && <div className="ui-pagehead__actions">{actions}</div>}
    </header>
  );
}

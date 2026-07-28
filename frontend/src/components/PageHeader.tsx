import { ReactNode } from "react";

export interface PageHeaderProps {
  /** 페이지 제목. 화면당 h1 은 이것 하나뿐이다. */
  title: string;
  /** 한 줄 설명 — 이 화면이 무엇을 하는 곳인지 학생·학부모 말로. */
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

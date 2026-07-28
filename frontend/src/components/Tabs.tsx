import { ReactNode } from "react";

export interface TabItem<K extends string = string> {
  key: K;
  label: ReactNode;
  /** 라벨 뒤에 붙는 건수 등. */
  count?: number;
}

export interface TabsProps<K extends string = string> {
  items: TabItem<K>[];
  value: K;
  onChange: (key: K) => void;
  /** 스크린리더용 그룹 이름. */
  label: string;
}

/** 탭. 좁은 화면에서는 가로 스크롤된다(hover 없이 탭으로만 동작). */
export function Tabs<K extends string = string>({ items, value, onChange, label }: TabsProps<K>) {
  return (
    <div className="ui-tabs" role="tablist" aria-label={label}>
      {items.map((item) => (
        <button
          key={item.key}
          type="button"
          role="tab"
          className="ui-tabs__tab"
          aria-selected={item.key === value}
          onClick={() => onChange(item.key)}
        >
          {item.label}
          {item.count !== undefined && <span className="num"> {item.count}</span>}
        </button>
      ))}
    </div>
  );
}

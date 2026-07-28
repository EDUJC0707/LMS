/**
 * 표. 정렬·빈 상태·선택 행을 내장한다.
 *
 *   <Table
 *     columns={[
 *       { key: "name",  header: "이름", cell: (r) => r.name },
 *       { key: "score", header: "점수", align: "right", numeric: true,
 *         sortValue: (r) => r.score, cell: (r) => r.score },
 *     ]}
 *     rows={rows}
 *     rowKey={(r) => r.id}
 *     empty="아직 응시한 시험이 없습니다."
 *   />
 *
 * 규약: 숫자 열에는 numeric 을 켠다 — 자릿수가 세로로 맞는다.
 */
import { ReactNode, useMemo, useState } from "react";

import { EmptyState } from "./States";

export interface Column<Row> {
  /** 열 식별자. 정렬 상태 저장에 쓴다. */
  key: string;
  header: ReactNode;
  cell: (row: Row, index: number) => ReactNode;
  align?: "left" | "right" | "center";
  /** 숫자 열 — 등폭·tabular-nums 로 렌더한다(점수·금액·시각·학번). */
  numeric?: boolean;
  /** 주면 이 열은 정렬 가능해진다. */
  sortValue?: (row: Row) => string | number;
  /** 열 폭 힌트(예: "8rem"). 생략하면 내용에 맞춘다. */
  width?: string;
}

export interface TableProps<Row> {
  columns: Column<Row>[];
  rows: Row[];
  rowKey: (row: Row, index: number) => string | number;
  /** 행이 없을 때 보여줄 문구 또는 EmptyState. */
  empty?: ReactNode;
  /** 행 클릭 — 주면 행 전체가 버튼처럼 동작한다(터치 대응). */
  onRowClick?: (row: Row) => void;
  /** 선택 표시할 행. */
  isSelected?: (row: Row) => boolean;
  /** 관리자 화면용 촘촘한 행 높이. */
  dense?: boolean;
  /** 표 설명(스크린리더). */
  caption?: string;
}

type SortState = { key: string; dir: "asc" | "desc" } | null;

export function Table<Row>({
  columns,
  rows,
  rowKey,
  empty = "표시할 내용이 없습니다.",
  onRowClick,
  isSelected,
  dense = false,
  caption,
}: TableProps<Row>) {
  const [sort, setSort] = useState<SortState>(null);

  const sorted = useMemo(() => {
    if (!sort) return rows;
    const column = columns.find((c) => c.key === sort.key);
    if (!column?.sortValue) return rows;
    const factor = sort.dir === "asc" ? 1 : -1;
    return [...rows].sort((a, b) => {
      const left = column.sortValue!(a);
      const right = column.sortValue!(b);
      if (typeof left === "number" && typeof right === "number") return (left - right) * factor;
      return String(left).localeCompare(String(right), "ko") * factor;
    });
  }, [rows, sort, columns]);

  const toggle = (key: string) =>
    setSort((prev) =>
      prev?.key === key ? { key, dir: prev.dir === "asc" ? "desc" : "asc" } : { key, dir: "asc" },
    );

  return (
    <div className="ui-tablewrap">
      <table className={`ui-table ${dense ? "ui-table--dense" : ""}`.trim()}>
        {caption && <caption className="sr-only">{caption}</caption>}
        <thead>
          <tr>
            {columns.map((column) => {
              const active = sort?.key === column.key;
              const ariaSort = active
                ? sort!.dir === "asc"
                  ? "ascending"
                  : "descending"
                : "none";
              return (
                <th
                  key={column.key}
                  scope="col"
                  style={{ width: column.width, textAlign: column.align }}
                  aria-sort={column.sortValue ? ariaSort : undefined}
                >
                  {column.sortValue ? (
                    <button
                      type="button"
                      className="ui-table__sort"
                      aria-sort={ariaSort}
                      onClick={() => toggle(column.key)}
                    >
                      {column.header}
                      <span aria-hidden="true">{active ? (sort!.dir === "asc" ? "▲" : "▼") : "↕"}</span>
                    </button>
                  ) : (
                    column.header
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {sorted.length === 0 ? (
            <tr className="ui-table__empty">
              <td colSpan={columns.length}>
                {typeof empty === "string" ? <EmptyState title={empty} /> : empty}
              </td>
            </tr>
          ) : (
            sorted.map((row, index) => (
              <tr
                key={rowKey(row, index)}
                className={isSelected?.(row) ? "is-selected" : undefined}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                style={onRowClick ? { cursor: "pointer" } : undefined}
              >
                {columns.map((column) => (
                  <td
                    key={column.key}
                    className={column.numeric ? "num" : undefined}
                    style={{ textAlign: column.align ?? (column.numeric ? "right" : undefined) }}
                  >
                    {column.cell(row, index)}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

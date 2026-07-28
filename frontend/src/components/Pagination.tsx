export interface PaginationProps {
  /** 1부터 시작. */
  page: number;
  /** 전체 페이지 수. 1 이하면 아무것도 그리지 않는다. */
  totalPages: number;
  onChange: (page: number) => void;
  /** "전체 128건" 같은 왼쪽 상태 문구. */
  status?: string;
}

function pageWindow(page: number, total: number): (number | "gap")[] {
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1);
  const out: (number | "gap")[] = [1];
  const start = Math.max(2, page - 1);
  const end = Math.min(total - 1, page + 1);
  if (start > 2) out.push("gap");
  for (let i = start; i <= end; i++) out.push(i);
  if (end < total - 1) out.push("gap");
  out.push(total);
  return out;
}

export function Pagination({ page, totalPages, onChange, status }: PaginationProps) {
  if (totalPages <= 1) return null;
  return (
    <nav className="ui-pagination" aria-label="페이지 이동">
      {status && <span className="ui-pagination__status">{status}</span>}
      <button
        type="button"
        className="ui-pagination__page"
        onClick={() => onChange(page - 1)}
        disabled={page <= 1}
        aria-label="이전 페이지"
      >
        ‹
      </button>
      {pageWindow(page, totalPages).map((item, index) =>
        item === "gap" ? (
          <span key={`gap-${index}`} className="ui-pagination__gap" aria-hidden="true">
            …
          </span>
        ) : (
          <button
            key={item}
            type="button"
            className="ui-pagination__page"
            aria-current={item === page ? "page" : undefined}
            onClick={() => onChange(item)}
          >
            {item}
          </button>
        ),
      )}
      <button
        type="button"
        className="ui-pagination__page"
        onClick={() => onChange(page + 1)}
        disabled={page >= totalPages}
        aria-label="다음 페이지"
      >
        ›
      </button>
    </nav>
  );
}

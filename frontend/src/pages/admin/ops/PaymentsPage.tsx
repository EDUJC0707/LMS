/**
 * 교재 결제·배부 상태 — GET /api/admin/payments (PRD 3.1.5, 기능 키 `결제확인`)
 *
 * as-is 가 *"결제내역 확인 후 배부"* 다. 이 화면이 그 확인 단계이므로
 * 중심은 목록이 아니라 **누가 냈고 누가 안 냈나**다.
 *
 * 서버가 페이지네이션한다(PageNumberPagination 20건) — 필터도 서버가 해석하므로
 * 화면에서 다시 거르지 않는다. 잘못된 값은 빈 목록이 아니라 400 으로 온다.
 */
import { useState } from "react";

import { http, useApi } from "../../../api";
import {
  Card,
  EmptyState,
  ErrorState,
  Field,
  Input,
  Loading,
  Pagination,
  Select,
  StatusBadge,
  Table,
} from "../../../components";
import "./ops.css";

interface PaymentRow {
  order_id: number;
  student: { id: number; name: string; matching_key: string };
  product_name: string;
  amount: number;
  status: string;
  is_billed: boolean;
  ordered_at: string | null;
  paid_at: string | null;
  delivered_at: string | null;
  payment: { provider: string; status: string; external_ref: string | null } | null;
}

interface Page {
  count: number;
  results: PaymentRow[];
}

const STATUSES = ["미결제", "결제완료", "배부완료", "취소"];

function day(value: string | null): string {
  return value ? value.slice(0, 10) : "—";
}

export default function PaymentsPage() {
  const [status, setStatus] = useState("");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);

  const list = useApi(
    async () =>
      (
        await http.get<Page>("/admin/payments", {
          params: { page, ...(status ? { status } : {}) },
        })
      ).data,
    [page, status],
  );

  // 이름 검색만 화면에서 한다 — 서버 필터에 이름 축이 없다(학생 번호는 있다).
  const needle = query.trim();
  const rows = (list.data?.results ?? []).filter(
    (row) => !needle || row.student.name.includes(needle),
  );

  return (
    <div className="ui-stack">
      <Card padding="none">
        <div className="ops-filters">
          <Field label="상태">
            {(field) => (
              <Select
                {...field}
                value={status}
                onChange={(event) => {
                  setStatus(event.target.value);
                  setPage(1);
                }}
              >
                <option value="">전체</option>
                {STATUSES.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Field label="학생">
            {(field) => (
              <Input
                {...field}
                value={query}
                onChange={(event) => setQuery(event.target.value)}
              />
            )}
          </Field>
        </div>

        {list.initialLoading ? (
          <Loading label="결제 내역을 불러오는 중…" />
        ) : list.error ? (
          <ErrorState description={list.error} onRetry={list.reload} />
        ) : rows.length === 0 ? (
          <EmptyState title="해당하는 결제가 없습니다" />
        ) : (
          <Table<PaymentRow>
            rows={rows}
            rowKey={(row) => row.order_id}
            caption="학생별 교재 결제·배부 상태"
            columns={[
              {
                key: "student",
                header: "학생",
                sortValue: (r) => r.student.name,
                cell: (r) => (
                  <span className="ops-name">
                    <span>{r.student.name}</span>
                    <span className="ops-sub num">{r.student.matching_key}</span>
                  </span>
                ),
              },
              { key: "product", header: "교재", cell: (r) => r.product_name },
              {
                key: "amount",
                header: "금액",
                align: "right",
                numeric: true,
                sortValue: (r) => r.amount,
                cell: (r) => r.amount.toLocaleString("ko-KR"),
              },
              {
                key: "status",
                header: "상태",
                align: "right",
                width: "7rem",
                cell: (r) => <StatusBadge status={r.status} />,
              },
              {
                key: "billed",
                header: "청구",
                align: "right",
                numeric: true,
                cell: (r) => (r.is_billed ? day(r.ordered_at) : "미발송"),
              },
              {
                key: "paid",
                header: "결제",
                align: "right",
                numeric: true,
                cell: (r) => day(r.paid_at),
              },
              {
                key: "ref",
                header: "승인번호",
                align: "right",
                cell: (r) => (
                  <span className="num">{r.payment?.external_ref ?? "—"}</span>
                ),
              },
            ]}
          />
        )}
      </Card>

      {list.data && (
        <Pagination
          page={page}
          totalPages={Math.ceil(list.data.count / 20)}
          onChange={setPage}
          status={`전체 ${list.data.count}건`}
        />
      )}
    </div>
  );
}

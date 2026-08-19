/**
 * 교재 결제·배부 상태 — GET /api/admin/payments (PRD 3.1.5, 기능 키 `결제확인`)
 *
 * as-is 가 *"결제내역 확인 후 배부"* 다. 이 화면이 그 확인 단계이므로
 * 중심은 목록이 아니라 **누가 냈고 누가 안 냈나**다.
 *
 * 서버가 페이지네이션한다(PageNumberPagination 20건) — 필터도 서버가 해석하므로
 * 화면에서 다시 거르지 않는다. 잘못된 값은 빈 목록이 아니라 400 으로 온다.
 *
 * **취소 버튼은 대표에게만 보인다.** 서버가 IsOwner 로 막고 있고(§2·§5),
 * 화면 숨김은 보조다 — 누를 수 없는 버튼을 그려 두면 눌러 보고 나서야 안다.
 *
 * **잔액 배너**: 자동충전을 안 켜기로 해서(2026-08-11) 잔액이 마르면 청구가
 * 통째로 멈춘다. 로그 말고 사람이 보는 자리가 여기다.
 *
 * **반 단위는 위 패널이 맡는다**(ClassGoodsPanel — FLOW §5-1). 아래 목록은
 * 주문 행이라 아직 주문이 없는 학생이 안 뜬다 — 청구를 시작하는 자리도,
 * 러셀 반의 일괄 배부도 거기여야 한다.
 */
import { useState } from "react";

import { http, useApi, useApiAction } from "../../../api";
import { useMe } from "../../../auth";
import {
  Alert,
  Button,
  Card,
  EmptyState,
  ErrorState,
  Input,
  Loading,
  Pagination,
  Select,
  StatusBadge,
  Table,
} from "../../../components";
import ClassGoodsPanel from "./ClassGoodsPanel";
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

interface BalanceInfo {
  balance: number | null;
  charge_url: string | null;
}

/** 이 아래로 떨어지면 배너를 띄운다 — 교재 몇 건 보내면 마르는 수준. */
const LOW_BALANCE = 50000;

export default function PaymentsPage() {
  const { me } = useMe();
  const isOwner = me?.role === "대표";
  const [status, setStatus] = useState("");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  // 어느 줄을 누르는 중인지 — 훅의 pending 은 페이지에 하나뿐이라 그것만
  // 물리면 모든 줄의 버튼이 함께 돈다.
  const [pendingId, setPendingId] = useState<number | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const balance = useApi(
    async () => (await http.get<BalanceInfo>("/admin/payments/balance")).data,
    [],
  );

  const list = useApi(
    async () =>
      (
        await http.get<Page>("/admin/payments", {
          params: { page, ...(status ? { status } : {}) },
        })
      ).data,
    [page, status],
  );

  // 값은 반드시 인자로 넘긴다 — 이 훅은 첫 렌더의 클로저를 붙든다(api/useApi.ts).
  //
  // **갱신된 행을 반드시 돌려준다.** `run` 은 실패하면 undefined 를 주는데
  // 액션이 아무것도 반환하지 않으면 성공도 undefined 라 둘을 구분할 수 없다 —
  // 그러면 성공한 뒤에도 실패로 보고 목록 새로고침을 건너뛴다(실측).
  const deliver = useApiAction(async (orderId: number) => {
    return (await http.post<PaymentRow>(`/admin/payments/${orderId}/deliver`)).data;
  });
  const cancel = useApiAction(async (orderId: number, reason: string) => {
    return (await http.post<PaymentRow>(`/admin/payments/${orderId}/cancel`, { reason })).data;
  });
  // 배부 표시는 우리 장부라 밖으로 나가는 것이 없다 — 사유도 확인창도 없다.
  const undeliver = useApiAction(async (orderId: number) => {
    return (await http.post<PaymentRow>(`/admin/payments/${orderId}/undeliver`)).data;
  });

  const runDeliver = async (row: PaymentRow) => {
    setNotice(null);
    setPendingId(row.order_id);
    const updated = await deliver.run(row.order_id);
    setPendingId(null);
    if (!updated) return; // 실패 사유는 위 Alert 에 뜬다
    setNotice(`${row.student.name} · ${row.product_name} 배부완료`);
    await list.reload();
  };

  const runUndeliver = async (row: PaymentRow) => {
    setNotice(null);
    setPendingId(row.order_id);
    const updated = await undeliver.run(row.order_id);
    setPendingId(null);
    if (!updated) return;
    setNotice(`${row.student.name} · ${row.product_name} 배부 해제`);
    await list.reload();
  };

  const runCancel = async (row: PaymentRow) => {
    // 돈이 되돌아가는 조작이라 사유를 받는다(서버도 필수로 요구한다 — §5 이력).
    const reason = window.prompt(`${row.student.name} 주문 취소 사유`);
    if (reason === null) return;
    setNotice(null);
    setPendingId(row.order_id);
    const updated = await cancel.run(row.order_id, reason);
    setPendingId(null);
    if (!updated) return;
    setNotice(`${row.student.name} · ${row.product_name} 취소`);
    await Promise.all([list.reload(), balance.reload()]);
  };

  // 이름 검색만 화면에서 한다 — 서버 필터에 이름 축이 없다(학생 번호는 있다).
  const needle = query.trim();
  const rows = (list.data?.results ?? []).filter(
    (row) => !needle || row.student.name.includes(needle),
  );

  const points = balance.data?.balance ?? null;

  return (
    <div className="ui-stack">
      {points !== null && points < LOW_BALANCE && (
        <Alert tone="warning">
          쌤포인트 잔액 {points.toLocaleString("ko-KR")}원
          {balance.data?.charge_url && (
            <>
              {" · "}
              <a href={balance.data.charge_url} target="_blank" rel="noreferrer">
                충전하기
              </a>
            </>
          )}
        </Alert>
      )}

      {(deliver.error || cancel.error || undeliver.error) && (
        <Alert
          tone="danger"
          onClose={() => {
            deliver.clearError();
            cancel.clearError();
            undeliver.clearError();
          }}
        >
          {deliver.error ?? cancel.error ?? undeliver.error}
        </Alert>
      )}

      {notice && (
        <Alert tone="success" onClose={() => setNotice(null)}>
          {notice}
        </Alert>
      )}

      <ClassGoodsPanel onChanged={() => void list.reload()} />

      <Card padding="none">
        {/* 필터 줄은 다른 운영 화면과 같은 부품을 쓴다(`ops-toolbar ops-cardbar`) —
            좌우 여백·간격·라벨 크기가 거기 한 곳에 있다. AttendancePage 선례. */}
        <div className="ops-toolbar ops-cardbar">
          <label className="ops-toolbar__field">
            <span className="ops-toolbar__label">상태</span>
            <Select
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
          </label>
          <label className="ops-toolbar__field">
            <span className="ops-toolbar__label">학생</span>
            <Input value={query} onChange={(event) => setQuery(event.target.value)} />
          </label>
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
              {
                key: "actions",
                header: "",
                align: "right",
                width: isOwner ? "11rem" : "6rem",
                cell: (r) => (
                  <>
                    {r.status === "결제완료" && (
                      <Button
                        size="sm"
                        loading={pendingId === r.order_id && deliver.pending}
                        onClick={() => runDeliver(r)}
                      >
                        배부완료
                      </Button>
                    )}
                    {r.status === "배부완료" && (
                      <Button
                        size="sm"
                        variant="ghost"
                        loading={pendingId === r.order_id && undeliver.pending}
                        onClick={() => runUndeliver(r)}
                      >
                        배부 해제
                      </Button>
                    )}
                    {/* 취소는 대표만. 서버가 IsOwner 로 막고 화면은 감추기만 한다. */}
                    {isOwner && r.status !== "취소" && (
                      <Button
                        size="sm"
                        variant="danger"
                        loading={pendingId === r.order_id && cancel.pending}
                        onClick={() => runCancel(r)}
                      >
                        취소
                      </Button>
                    )}
                  </>
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

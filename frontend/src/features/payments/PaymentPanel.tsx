/**
 * 교재 결제 패널 — 학생 화면과 학부모 화면이 공유한다 (PRD 3.1.5·3.2.5·3.4).
 *
 * 두 화면이 각자 표를 그리면 같은 주문이 한쪽에만 보이는 식으로 갈린다.
 * 다른 것은 **어느 경로로 청구를 개시하느냐** 뿐이라 그것만 prop 으로 받는다.
 *
 * 결제창은 모달 안 iframe 이다 — PRD 3.2.5 *"외부 사이트로 완전히 이탈하지 않고
 * LMS 흐름 내 진행"*. 다만 결제 페이지가 프레이밍을 막을 수 있어(X-Frame-Options)
 * 새 창 링크를 함께 둔다. 링크가 없으면 막혔을 때 **빈 사각형만 남는다**.
 */
import { useState } from "react";

import { http, useApi, useApiAction } from "../../api";
import {
  Alert,
  Button,
  Card,
  EmptyState,
  ErrorState,
  Loading,
  Modal,
  StatusBadge,
  Table,
} from "../../components";

export interface PaymentOrder {
  order_id: number;
  product_name: string;
  amount: number;
  status: string;
  ordered_at: string | null;
  paid_at: string | null;
  delivered_at: string | null;
}

export interface PurchasableProduct {
  product_id: number;
  name: string;
  price: number;
}

interface BillResult {
  order_id: number;
  pay_url: string | null;
  status: string;
}

/** 45000 → "45,000원" */
export function won(amount: number): string {
  return `${amount.toLocaleString("ko-KR")}원`;
}

/** ISO → "2026-08-05" (시각까지는 필요 없다 — 날짜 단위로 읽는 값이다) */
function day(value: string | null): string {
  return value ? value.slice(0, 10) : "—";
}

export interface PaymentPanelProps {
  /** 주문 목록 조회 경로 — /student/payments 또는 /parent/payments */
  ordersPath: string;
  /** 청구 개시 경로 — /student/payments/bill 또는 /parent/payments/bill */
  billPath: string;
  /** 학부모 화면에서만 실린다. 없으면 붙이지 않는다. */
  studentId?: number | null;
}

export function PaymentPanel({ ordersPath, billPath, studentId }: PaymentPanelProps) {
  // 어느 교재를 누르는 중인지 — 훅의 pending 은 페이지에 하나뿐이라 그것만
  // 물리면 모든 행의 버튼이 함께 돈다.
  const [pendingProductId, setPendingProductId] = useState<number | null>(null);
  const [payUrl, setPayUrl] = useState<string | null>(null);

  const params = studentId != null ? { student_id: studentId } : undefined;

  const orders = useApi(
    () => http.get<PaymentOrder[]>(ordersPath, { params }).then((r) => r.data),
    [ordersPath, studentId],
  );
  const products = useApi(
    () => http.get<PurchasableProduct[]>("/payments/products").then((r) => r.data),
    [],
  );

  // 값은 반드시 인자로 넘긴다 — 이 훅은 첫 렌더의 클로저를 붙들기 때문에
  // 바깥 상태를 읽으면 항상 처음 값이 나간다(api/useApi.ts).
  const bill = useApiAction(async (productId: number) => {
    const body: Record<string, number> = { product_id: productId };
    if (studentId != null) body.student_id = studentId;
    const response = await http.post<BillResult>(billPath, body);
    return response.data;
  });

  const buy = async (product: PurchasableProduct) => {
    setPendingProductId(product.product_id);
    const created = await bill.run(product.product_id);
    setPendingProductId(null);
    if (!created) return; // 실패 사유는 위 Alert 에 뜬다
    setPayUrl(created.pay_url);
    await orders.reload();
  };

  // 활성 주문이 있는 교재는 다시 살 수 없다(중복 청구 차단은 서버가 하지만,
  // 누를 수 없는 버튼을 그려 두면 눌러 보고 나서야 알게 된다).
  const billedProductNames = new Set(
    (orders.data ?? []).filter((o) => o.status !== "취소").map((o) => o.product_name),
  );
  const buyable = (products.data ?? []).filter((p) => !billedProductNames.has(p.name));

  return (
    <div className="ui-stack">
      {bill.error && (
        <Alert tone="danger" onClose={bill.clearError}>
          {bill.error}
        </Alert>
      )}

      {buyable.length > 0 && (
        <Card title="교재 구매" padding="none">
          <Table<PurchasableProduct>
            rows={buyable}
            rowKey={(row) => row.product_id}
            caption="구매할 수 있는 교재"
            columns={[
              { key: "name", header: "교재", cell: (row) => row.name },
              {
                key: "price",
                header: "가격",
                align: "right",
                numeric: true,
                cell: (row) => won(row.price),
              },
              {
                key: "buy",
                header: "",
                align: "right",
                width: "8rem",
                cell: (row) => (
                  <Button
                    size="sm"
                    variant="primary"
                    loading={pendingProductId === row.product_id}
                    onClick={() => buy(row)}
                  >
                    구매
                  </Button>
                ),
              },
            ]}
          />
        </Card>
      )}

      <Card title="결제 내역" padding="none">
        {orders.initialLoading ? (
          <Loading label="결제 내역을 불러오는 중…" />
        ) : orders.error ? (
          <ErrorState description={orders.error} onRetry={orders.reload} />
        ) : (orders.data ?? []).length === 0 ? (
          <EmptyState title="아직 결제 내역이 없습니다" />
        ) : (
          <Table<PaymentOrder>
            rows={orders.data ?? []}
            rowKey={(row) => row.order_id}
            caption="교재 결제·배부 상태"
            columns={[
              { key: "product", header: "교재", cell: (row) => row.product_name },
              {
                key: "amount",
                header: "금액",
                align: "right",
                numeric: true,
                cell: (row) => won(row.amount),
              },
              {
                key: "status",
                header: "상태",
                align: "right",
                width: "8rem",
                cell: (row) => <StatusBadge status={row.status} />,
              },
              {
                key: "ordered",
                header: "청구",
                align: "right",
                numeric: true,
                cell: (row) => day(row.ordered_at),
              },
              {
                key: "paid",
                header: "결제",
                align: "right",
                numeric: true,
                cell: (row) => day(row.paid_at),
              },
            ]}
          />
        )}
      </Card>

      {payUrl && (
        <Modal open title="교재 결제" wide onClose={() => setPayUrl(null)}>
          <iframe
            src={payUrl}
            title="교재 결제"
            style={{ width: "100%", height: "70vh", border: 0 }}
          />
          <p style={{ marginTop: "var(--space-md)" }}>
            <a href={payUrl} target="_blank" rel="noreferrer">
              새 창에서 열기
            </a>
          </p>
        </Modal>
      )}
    </div>
  );
}

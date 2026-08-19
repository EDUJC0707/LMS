/**
 * 반 하나의 교재 — 누가 샀나 · 배부 (FLOW §5-1 반 레벨, 2-5, 2-7)
 *
 *   GET  /api/admin/payments/classes
 *   GET  /api/admin/payments/classes/{id}
 *   POST /api/admin/payments/classes/{id}/deliver     일괄 배부
 *   POST /api/admin/payments/classes/{id}/undeliver   일괄 배부 해제
 *   POST /api/admin/payments/bill                     학생 하나 청구
 *
 * **청구는 개별이고 배부는 묶음이다**(FLOW §5). 학생마다 낼 것이 다르고 잘못
 * 나간 청구는 되돌리기가 또 밖으로 나가므로 청구 버튼은 학생 행에 하나씩
 * 붙는다. 배부는 "이 반 전원이 샀다" 라는 사실이라 묶는다.
 *
 * **러셀 반에는 청구 버튼이 없다**(uses_payssam=false — FLOW 2-7). 서버가
 * check_billable 로 막고 화면은 감추기만 한다. 그 반에서 주문이 생기는 길은
 * 일괄 배부 하나뿐이다.
 *
 * 주문 맵의 키는 **문자열**이다 — 서버가 숫자 키로 내려도 JSON 을 지나면
 * 문자열이 된다.
 */
import { useState } from "react";

import { http, useApi, useApiAction } from "../../../api";
import {
  Alert,
  Button,
  Card,
  EmptyState,
  ErrorState,
  Loading,
  Select,
  StatusBadge,
  Table,
} from "../../../components";
import "./ops.css";

interface ClassRow {
  class_id: number;
  name: string;
  course_name: string;
  uses_payssam: boolean;
}

interface ProductRow {
  product_id: number;
  name: string;
  kind: string;
  price: number;
}

interface HeldOrder {
  order_id: number;
  status: string;
  is_billed: boolean;
}

interface StudentRow {
  student_id: number;
  name: string;
  matching_key: string;
  orders: Record<string, HeldOrder | undefined>;
}

interface ClassGoods {
  class: ClassRow;
  products: ProductRow[];
  students: StudentRow[];
}

export default function ClassGoodsPanel({ onChanged }: { onChanged: () => void }) {
  const [classId, setClassId] = useState("");
  const [productId, setProductId] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const [pendingId, setPendingId] = useState<number | null>(null);

  const classes = useApi(
    async () => (await http.get<ClassRow[]>("/admin/payments/classes")).data,
    [],
  );

  const goods = useApi(async () => {
    if (!classId) return null;
    return (await http.get<ClassGoods>(`/admin/payments/classes/${classId}`)).data;
  }, [classId]);

  // 값은 인자로 넘긴다 — 이 훅은 첫 렌더의 클로저를 붙든다(api/useApi.ts).
  const bill = useApiAction(async (studentId: number, product: number) => {
    await http.post("/admin/payments/bill", {
      student_id: studentId,
      product_id: product,
    });
    return true;
  });
  const mark = useApiAction(async (orderId: number, verb: string) => {
    await http.post(`/admin/payments/${orderId}/${verb}`);
    return true;
  });
  const batch = useApiAction(async (klass: string, product: number, verb: string) => {
    return (
      await http.post<{ delivered?: number; skipped?: number; undelivered?: number }>(
        `/admin/payments/classes/${klass}/${verb}`,
        { product_id: product },
      )
    ).data;
  });

  const detail = goods.data ?? null;
  const products = detail?.products ?? [];
  const product = products.find((p) => String(p.product_id) === productId) ?? null;
  const usesPayssam = detail?.class.uses_payssam ?? false;

  const refresh = async () => {
    await goods.reload();
    onChanged();
  };

  const runBill = async (row: StudentRow) => {
    if (!product) return;
    setNotice(null);
    setPendingId(row.student_id);
    const ok = await bill.run(row.student_id, product.product_id);
    setPendingId(null);
    if (!ok) return;
    setNotice(`${row.name} · ${product.name} 청구`);
    await refresh();
  };

  const runMark = async (row: StudentRow, orderId: number, verb: "deliver" | "undeliver") => {
    setNotice(null);
    setPendingId(row.student_id);
    const ok = await mark.run(orderId, verb);
    setPendingId(null);
    if (!ok) return;
    setNotice(`${row.name} · ${verb === "deliver" ? "배부완료" : "배부 해제"}`);
    await refresh();
  };

  const runBatch = async (verb: "deliver" | "undeliver") => {
    if (!product || !classId) return;
    setNotice(null);
    const result = await batch.run(classId, product.product_id, verb);
    if (!result) return;
    setNotice(
      verb === "deliver"
        ? `배부완료 ${result.delivered ?? 0}건${result.skipped ? ` · 주문 없음 ${result.skipped}건` : ""}`
        : `배부 해제 ${result.undelivered ?? 0}건`,
    );
    await refresh();
  };

  const rows = detail?.students ?? [];

  return (
    <Card padding="none">
      <div className="ops-toolbar ops-cardbar">
        <label className="ops-toolbar__field">
          <span className="ops-toolbar__label">반</span>
          <Select
            value={classId}
            onChange={(event) => {
              setClassId(event.target.value);
              setProductId("");
              setNotice(null);
            }}
          >
            <option value="">선택</option>
            {(classes.data ?? []).map((row) => (
              <option key={row.class_id} value={row.class_id}>
                {row.course_name} · {row.name}
              </option>
            ))}
          </Select>
        </label>
        <label className="ops-toolbar__field">
          <span className="ops-toolbar__label">교재</span>
          <Select
            value={productId}
            onChange={(event) => {
              setProductId(event.target.value);
              setNotice(null);
            }}
            disabled={products.length === 0}
          >
            <option value="">선택</option>
            {products.map((row) => (
              <option key={row.product_id} value={row.product_id}>
                {row.name} · {row.price.toLocaleString("ko-KR")}원
              </option>
            ))}
          </Select>
        </label>
        {product && (
          <>
            <Button size="sm" loading={batch.pending} onClick={() => runBatch("deliver")}>
              일괄 배부
            </Button>
            <Button
              size="sm"
              variant="ghost"
              loading={batch.pending}
              onClick={() => runBatch("undeliver")}
            >
              일괄 배부 해제
            </Button>
          </>
        )}
      </div>

      {(bill.error || batch.error || mark.error) && (
        <Alert
          tone="danger"
          onClose={() => {
            bill.clearError();
            batch.clearError();
            mark.clearError();
          }}
        >
          {bill.error ?? batch.error ?? mark.error}
        </Alert>
      )}
      {notice && (
        <Alert tone="success" onClose={() => setNotice(null)}>
          {notice}
        </Alert>
      )}

      {goods.initialLoading ? (
        <Loading label="명단을 불러오는 중…" />
      ) : goods.error ? (
        <ErrorState description={goods.error} onRetry={goods.reload} />
      ) : !detail ? null : rows.length === 0 ? (
        <EmptyState title="이 반에 학생이 없습니다" />
      ) : (
        <Table<StudentRow>
          rows={rows}
          rowKey={(row) => row.student_id}
          caption="반별 교재 구입·배부 상태"
          columns={[
            {
              key: "student",
              header: "학생",
              cell: (row) => (
                <span className="ops-name">
                  <span>{row.name}</span>
                  <span className="ops-sub num">{row.matching_key}</span>
                </span>
              ),
            },
            {
              key: "status",
              header: "상태",
              align: "right",
              width: "8rem",
              cell: (row) => {
                const held = product ? row.orders[String(product.product_id)] : undefined;
                return held ? <StatusBadge status={held.status} /> : null;
              },
            },
            {
              key: "actions",
              header: "",
              align: "right",
              width: "7rem",
              cell: (row) => {
                if (!product) return null;
                const held = row.orders[String(product.product_id)];
                const busy = pendingId === row.student_id;
                if (!held) {
                  // 러셀 반은 청구가 나가면 안 된다(FLOW 2-7) — 서버도 막는다.
                  return usesPayssam ? (
                    <Button size="sm" loading={busy && bill.pending} onClick={() => runBill(row)}>
                      청구
                    </Button>
                  ) : null;
                }
                if (held.status === "결제완료") {
                  return (
                    <Button
                      size="sm"
                      loading={busy && mark.pending}
                      onClick={() => runMark(row, held.order_id, "deliver")}
                    >
                      배부완료
                    </Button>
                  );
                }
                if (held.status === "배부완료") {
                  return (
                    <Button
                      size="sm"
                      variant="ghost"
                      loading={busy && mark.pending}
                      onClick={() => runMark(row, held.order_id, "undeliver")}
                    >
                      배부 해제
                    </Button>
                  );
                }
                return null;
              },
            },
          ]}
        />
      )}
    </Card>
  );
}

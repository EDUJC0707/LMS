/**
 * 동보 — 결석 학생의 복습영상 신청 내역.
 *
 * 호출: GET  /api/admin/makeup-requests
 *      · POST /api/admin/makeup-requests/{id}/reject
 *
 * **승인이 없다**(FLOW 3-4). 신청 + 결석 확인이 차면 서버가 알아서 지급하므로
 * 이 화면은 그 결과를 보는 자리다. `신청` 으로 남는 것은 결석이 확정되지 않은
 * 신청뿐이고, 거절은 그것을 닫는 유일한 손이다 — 되돌릴 수 없어 확인 모달을 둔다.
 */
import { useMemo, useState } from "react";

import { http, useApi, useApiAction } from "../../../api";
import {
  Alert,
  Button,
  Card,
  ErrorState,
  Loading,
  Modal,
  StatusBadge,
  Table,
  Tabs,
} from "../../../components";
import type { Column } from "../../../components";
import { shortDate, stamp } from "./format";
import "./ops.css";
import type { MakeupRow, MakeupStatus } from "./types";

type Tab = MakeupStatus | "전체";
const TABS: Tab[] = ["신청", "지급완료", "거절", "전체"];

export default function MakeupOpsPage() {
  const [tab, setTab] = useState<Tab>("신청");
  const [rejecting, setRejecting] = useState<MakeupRow | null>(null);

  const list = useApi(
    async () =>
      (await http.get<{ requests: MakeupRow[] }>("/admin/makeup-requests")).data.requests,
    [],
  );

  const all = useMemo(() => list.data ?? [], [list.data]);
  const countOf = (key: Tab) =>
    key === "전체" ? all.length : all.filter((r) => r.status === key).length;
  const rows = useMemo(
    () => (tab === "전체" ? all : all.filter((r) => r.status === tab)),
    [all, tab],
  );

  const reject = useApiAction(async (row: MakeupRow) => {
    await http.post(`/admin/makeup-requests/${row.makeup_id}/reject`);
  });

  const runReject = async (row: MakeupRow) => {
    await reject.run(row);
    setRejecting(null);
    void list.reload();
  };

  const columns: Column<MakeupRow>[] = [
    {
      key: "student",
      header: "학생",
      sortValue: (r) => r.student.name ?? "",
      cell: (r) => (
        <span className="ops-name">
          <span>{r.student.name ?? "이름 미등록"}</span>
          <span className="ops-sub num">{r.student.login_id ?? r.student.matching_key}</span>
        </span>
      ),
    },
    {
      key: "session",
      header: "결석한 수업",
      sortValue: (r) => r.session_date ?? "",
      cell: (r) => (
        <span className="ops-name">
          <span>{shortDate(r.session_date)}</span>
          <span className="ops-sub">
            {r.course_name ?? "강좌 미매핑"}
            {r.week_no !== null ? ` ${r.week_no}주차` : ""}
          </span>
        </span>
      ),
    },
    {
      key: "source",
      header: "신청 경로",
      width: "11rem",
      cell: (r) => (
        <span className="ops-name">
          <span>{r.source}</span>
          {r.requested_by && <span className="ops-sub">{r.requested_by}</span>}
        </span>
      ),
    },
    {
      key: "created",
      header: "신청 시각",
      width: "9rem",
      sortValue: (r) => r.created_at,
      cell: (r) => <span className="ops-sub">{stamp(r.created_at)}</span>,
    },
    {
      key: "status",
      header: "상태",
      width: "10rem",
      cell: (r) => (
        <span className="ops-name">
          <StatusBadge status={r.status} />
          {r.granted_at && <span className="ops-sub">{stamp(r.granted_at)}</span>}
        </span>
      ),
    },
    {
      key: "act",
      header: "처리",
      align: "right",
      width: "12rem",
      cell: (r) =>
        r.status === "신청" ? (
          <span className="ui-row" style={{ justifyContent: "flex-end" }}>
            <Button size="sm" variant="ghost" onClick={() => setRejecting(r)}>
              거절
            </Button>
          </span>
        ) : (
          <span className="ops-dash">처리 완료</span>
        ),
    },
  ];

  return (
    <>
      <div className="ui-stack">
        {reject.error && !rejecting && <Alert tone="danger">{reject.error}</Alert>}

        {list.loading ? (
          <Loading label="신청 목록을 불러오는 중…" />
        ) : list.error ? (
          <ErrorState description={list.error} onRetry={list.reload} />
        ) : (
          <Card padding="none" className="ops-tablecard">
            <div className="ops-cardbar ops-cardbar--tabs">
              <Tabs
                label="신청 상태"
                value={tab}
                onChange={setTab}
                items={TABS.map((key) => ({ key, label: key, count: countOf(key) }))}
              />
            </div>
            <Table
              caption="동보 신청 목록"
              dense
              columns={columns}
              rows={rows}
              rowKey={(r) => r.makeup_id}
              empty={
                tab === "전체" ? "동보 신청이 없습니다" : `${tab} 상태인 신청이 없습니다`
              }
            />
          </Card>
        )}
      </div>

      <Modal
        open={rejecting !== null}
        onClose={() => setRejecting(null)}
        title="이 신청을 거절할까요?"
        footer={
          <>
            <Button variant="ghost" onClick={() => setRejecting(null)}>
              그만두기
            </Button>
            <Button
              variant="danger"
              loading={reject.pending}
              onClick={() => rejecting && void runReject(rejecting)}
            >
              거절하기
            </Button>
          </>
        }
      >
        {rejecting && (
          <div className="ui-stack ui-stack--sm">
            {reject.error && <Alert tone="danger">{reject.error}</Alert>}
            <p>
              {rejecting.student.name ?? "학생"}(원번 {rejecting.student.login_id ?? rejecting.student.matching_key})의{" "}
              {shortDate(rejecting.session_date)} 결석 동보 신청입니다.
            </p>
          </div>
        )}
      </Modal>
    </>
  );
}

/**
 * 결석 상담 대기열 — 출결에서 결석을 저장하면 자동으로 만들어지는 학부모 통화 카드.
 *
 * 호출: GET   /api/admin/counseling/queue
 *      · PATCH /api/admin/counseling/{counsel_id}
 *
 * 3회 정책을 화면에 드러낸다: 미연결로 기록하면 재시도 카드가 생기고,
 * 3회째 미연결이면 알림톡 안내로 종결된다(백엔드 MAX_CALL_ATTEMPTS=3).
 */
import { useEffect, useMemo, useRef, useState } from "react";

import { http, useApi, useApiAction } from "../../../api";
import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  ErrorState,
  Field,
  Input,
  Loading,
  PageHeader,
  Radio,
  Select,
  Table,
  Textarea,
} from "../../../components";
import type { Column } from "../../../components";
import { shortDate, stamp } from "./format";
import "./ops.css";
import type { CounselCard, CounselRecordResult } from "./types";
import { MAX_CALL_ATTEMPTS } from "./types";

type CallResult = "연결" | "미연결";

export default function CounselingPage() {
  const [dateFilter, setDateFilter] = useState("");
  const [query, setQuery] = useState("");
  const [target, setTarget] = useState<CounselCard | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const queue = useApi(
    async () => (await http.get<{ queue: CounselCard[] }>("/admin/counseling/queue")).data.queue,
    [],
  );

  const all = useMemo(() => queue.data ?? [], [queue.data]);

  const dates = useMemo(() => {
    const seen = new Set<string>();
    for (const card of all) if (card.absence_date) seen.add(card.absence_date);
    return [...seen].sort().reverse();
  }, [all]);

  const rows = useMemo(() => {
    const needle = query.trim();
    return all.filter((card) => {
      if (dateFilter && card.absence_date !== dateFilter) return false;
      if (!needle) return true;
      return (
        (card.student.name ?? "").includes(needle) || card.student.unique_id.includes(needle)
      );
    });
  }, [all, dateFilter, query]);

  const columns: Column<CounselCard>[] = [
    {
      key: "student",
      header: "학생",
      sortValue: (r) => r.student.name ?? "",
      cell: (r) => (
        <span className="ops-name">
          <span>{r.student.name ?? "이름 미등록"}</span>
          <span className="ops-sub num">{r.student.unique_id}</span>
        </span>
      ),
    },
    {
      key: "absence",
      header: "결석한 수업일",
      width: "11rem",
      sortValue: (r) => r.absence_date ?? "",
      cell: (r) => shortDate(r.absence_date),
    },
    {
      key: "target",
      header: "통화 대상",
      width: "8rem",
      cell: (r) => r.target,
    },
    {
      key: "attempts",
      header: "통화 시도",
      width: "14rem",
      sortValue: (r) => r.attempts,
      cell: (r) => (
        <span className="ops-name">
          <span className="num">
            {r.attempts}/{MAX_CALL_ATTEMPTS}
          </span>
          {r.attempts === 0 ? (
            <span className="ops-sub">첫 통화</span>
          ) : r.attempts >= MAX_CALL_ATTEMPTS - 1 ? (
            <Badge tone="warning">이번에 안 되면 문자 종결</Badge>
          ) : (
            <span className="ops-sub">재시도</span>
          )}
        </span>
      ),
    },
    {
      key: "created",
      header: "카드 생성",
      width: "9rem",
      sortValue: (r) => r.created_at,
      cell: (r) => <span className="ops-sub">{stamp(r.created_at)}</span>,
    },
    {
      key: "act",
      header: "기록",
      align: "right",
      width: "10rem",
      cell: (r) => (
        <Button size="sm" onClick={() => setTarget(r)}>
          통화 결과 입력
        </Button>
      ),
    },
  ];

  return (
    <>
      <PageHeader
        title="결석 상담 대기열"
      />

      <div className="ui-stack">
        {notice && (
          <Alert tone="success" onClose={() => setNotice(null)}>
            {notice}
          </Alert>
        )}

        {queue.loading ? (
          <Loading label="대기열을 불러오는 중…" />
        ) : queue.error ? (
          <ErrorState description={queue.error} onRetry={queue.reload} />
        ) : (
          <>
            {target && (
              <RecordPanel
                key={target.counsel_id}
                card={target}
                onClose={() => setTarget(null)}
                onDone={(message) => {
                  setTarget(null);
                  setNotice(message);
                  void queue.reload();
                }}
              />
            )}

            <Card padding="none">
            <div
              className="ops-toolbar"
              style={{ padding: "var(--space-sm) var(--space-md)", alignItems: "flex-end" }}
            >
              <label className="ops-toolbar__field">
                <span className="ops-toolbar__label">결석한 수업일</span>
                <Select value={dateFilter} onChange={(event) => setDateFilter(event.target.value)}>
                  <option value="">전체 ({all.length}건)</option>
                  {dates.map((date) => (
                    <option key={date} value={date}>
                      {shortDate(date)} ({all.filter((c) => c.absence_date === date).length}건)
                    </option>
                  ))}
                </Select>
              </label>
              <label className="ops-toolbar__field">
                <span className="ops-toolbar__label">학생 찾기</span>
                <Input
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="이름 또는 원번"
                />
              </label>
              {(dateFilter || query) && (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    setDateFilter("");
                    setQuery("");
                  }}
                >
                  조건 지우기
                </Button>
              )}
            </div>

            <Table
              caption="결석 상담 대기 카드"
              dense
              columns={columns}
              rows={rows}
              rowKey={(r) => r.counsel_id}
              isSelected={(r) => r.counsel_id === target?.counsel_id}
              empty={
                all.length === 0 ? "통화할 대기 카드가 없습니다" : "조건에 맞는 카드가 없습니다"
              }
            />

            </Card>
          </>
        )}
      </div>
    </>
  );
}

function RecordPanel({
  card,
  onClose,
  onDone,
}: {
  card: CounselCard;
  onClose: () => void;
  onDone: (message: string) => void;
}) {
  const [result, setResult] = useState<CallResult>("연결");
  const [reason, setReason] = useState("");
  const [memo, setMemo] = useState("");
  const [followUp, setFollowUp] = useState("");
  const [makeupRequested, setMakeupRequested] = useState(false);
  const anchor = useRef<HTMLDivElement>(null);

  // 표 아래쪽 카드를 눌러도 기록 폼이 눈에 들어오게 한다.
  useEffect(() => {
    anchor.current?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, []);

  const record = useApiAction(async () => {
    const { data } = await http.patch<CounselRecordResult>(`/admin/counseling/${card.counsel_id}`, {
      result,
      absence_reason: result === "연결" ? reason : "",
      call_memo: memo,
      follow_up_action: result === "연결" ? followUp : "",
      makeup_requested: result === "연결" ? makeupRequested : false,
    });
    return data;
  });

  const submit = async () => {
    const data = await record.run();
    if (!data) return;
    const name = card.student.name ?? "학생";
    if (data.closed_by_sms) {
      onDone(
        `${name} 학부모 통화 ${data.attempts}회 시도 — 알림톡 종결`,
      );
      return;
    }
    if (data.next_counsel_id) {
      onDone(
        `${name} 학부모 미연결 — 재시도 카드 생성(${data.attempts}회 시도)`,
      );
      return;
    }
    onDone(
      `${name} 학부모 통화 기록${data.makeup_requested ? " · 동보 희망" : ""}`,
    );
  };

  return (
    <Card
      title={`${card.student.name ?? "학생"} · ${card.target} 통화 기록`}
      aside={`원번 ${card.student.unique_id} · ${shortDate(card.absence_date)} 결석 · 지금까지 ${card.attempts}회 시도`}
    >
      <div className="ui-stack ui-stack--md" ref={anchor}>
        {record.error && <Alert tone="danger">{record.error}</Alert>}

        <div className="ops-toolbar__field">
          <span className="ops-toolbar__label">통화 결과</span>
          <div className="ui-row">
            <Radio
              name={`call-${card.counsel_id}`}
              label="연결됐습니다"
              checked={result === "연결"}
              onChange={() => setResult("연결")}
            />
            <Radio
              name={`call-${card.counsel_id}`}
              label="연결되지 않았습니다"
              checked={result === "미연결"}
              onChange={() => setResult("미연결")}
            />
          </div>
        </div>

        {result === "연결" ? (
          <>
            <div className="ui-grid">
              <Field label="결석 사유">
                {(props) => (
                  <Input
                    {...props}
                    value={reason}
                    onChange={(event) => setReason(event.target.value)}
                  />
                )}
              </Field>

              <Field label="후속 조치">
                {(props) => (
                  <Input
                    {...props}
                    value={followUp}
                    onChange={(event) => setFollowUp(event.target.value)}
                  />
                )}
              </Field>
            </div>

            <Field label="통화 내용">
              {(props) => (
                <Textarea
                  {...props}
                  rows={2}
                  value={memo}
                  onChange={(event) => setMemo(event.target.value)}
                />
              )}
            </Field>

            <Checkbox
              checked={makeupRequested}
              onChange={(event) => setMakeupRequested(event.target.checked)}
              label="복습영상(동보) 요청"
            />
          </>
        ) : (
          <>
            <Field label="시도 메모">
              {(props) => (
                <Textarea
                  {...props}
                  rows={2}
                  value={memo}
                  onChange={(event) => setMemo(event.target.value)}
                />
              )}
            </Field>
            <Alert tone="warning">
              {`${card.attempts + 1}/${MAX_CALL_ATTEMPTS}회째 시도`}
            </Alert>
          </>
        )}

        <div className="ui-row" style={{ justifyContent: "flex-end" }}>
          <Button variant="ghost" onClick={onClose}>
            닫기
          </Button>
          <Button variant="primary" loading={record.pending} onClick={() => void submit()}>
            기록 저장
          </Button>
        </div>
      </div>
    </Card>
  );
}

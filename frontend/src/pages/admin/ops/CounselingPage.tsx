/**
 * 결석 상담 대기열 — 출결에서 결석을 저장하면 자동으로 만들어지는 학부모 통화 카드.
 *
 * 호출: GET   /api/admin/counseling/queue
 *      · PATCH /api/admin/counseling/{counsel_id}
 *
 * 화면 흐름(2026-08-12 확정):
 *   ① 채널톡 통화 기록을 며칠치 보여준다 — 누르면 그 통화의 전사가 열린다
 *   ② 조교가 **시도 횟수를 직접 넣는다**(− N +). 기계가 세지 않는 이유는
 *      화면이 보여준 목록과 어긋나면 어느 쪽이 맞는지 알 수 없기 때문이다
 *   ③ 3회부터 `결석 안내 보내기` 가 켜진다. **한 번만** 나가고, 보낸 뒤에도
 *      통화는 더 걸 수 있다(4회째도 가능) — 3회는 마감이 아니라 신호다
 * **문자는 자동으로 안 나간다.** 닫는 것도 보내는 것도 사람이 누른다.
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
  Radio,
  Select,
  Table,
  Textarea,
} from "../../../components";
import type { Column } from "../../../components";
import { shortDate, stamp } from "./format";
import "./ops.css";
import type {
  CounselCall,
  CounselCard,
  CounselRecordResult,
  CounselTranscript,
} from "./types";
import { MAX_CALL_ATTEMPTS } from "./types";

type CallResult = "연결" | "미연결" | "종결";

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

  // 발송·학생 2차는 표에서 바로 누른다 — 통화 결과 폼을 열 필요가 없는 동작이다.
  const notify = useApiAction(async (id: number) => {
    await http.post(`/admin/counseling/${id}/notify`);
  });
  const openStudent = useApiAction(async (id: number) => {
    await http.post("/admin/counseling", { from_counsel_id: id, target: "학생" });
  });

  const send = async (card: CounselCard) => {
    if (!(await notify.run(card.counsel_id))) return;
    setNotice(`${card.student.name ?? "학생"} 학부모에게 결석 안내를 보냈습니다`);
    void queue.reload();
  };

  const toStudent = async (card: CounselCard) => {
    if (!(await openStudent.run(card.counsel_id))) return;
    setNotice(`${card.student.name ?? "학생"} 학생 통화 카드를 열었습니다`);
    void queue.reload();
  };

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
        (card.student.name ?? "").includes(needle) || (card.student.login_id ?? "").includes(needle)
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
          <span className="ops-sub num">{r.student.login_id ?? r.student.matching_key}</span>
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
            <Badge tone="warning">3회 — 닫아도 됩니다</Badge>
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
      cell: (r) =>
        r.attempts >= MAX_CALL_ATTEMPTS && !r.notified ? (
          <Button
            size="sm"
            variant="primary"
            loading={notify.pending}
            onClick={() => void send(r)}
          >
            결석 안내 보내기
          </Button>
        ) : (
          <span className="ui-row">
            <Button size="sm" onClick={() => setTarget(r)}>
              통화 결과 입력
            </Button>
            {r.target === "학부모" && (
              <Button size="sm" variant="ghost" loading={openStudent.pending} onClick={() => void toStudent(r)}>
                학생에게
              </Button>
            )}
          </span>
        ),
    },
  ];

  return (
    <>
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

            <Card padding="none" className="ops-tablecard">
              <div className="ops-toolbar ops-cardbar">
                <label className="ops-toolbar__field">
                  <span className="ops-toolbar__label">결석한 수업일</span>
                  <Select
                    value={dateFilter}
                    onChange={(event) => setDateFilter(event.target.value)}
                  >
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

  // 조교가 방금 건 통화를 채널톡에서 찾아 결과를 미리 채운다. 못 찾아도
  // 폼은 그대로 쓴다 — 개인 전화로 걸었거나 로그가 아직 안 올라온 것뿐이다.
  const calls = useApi(
    async () =>
      (
        await http.get<{ calls: CounselCall[] }>(
          `/admin/counseling/${card.counsel_id}/calls`,
        )
      ).data.calls,
    [card.counsel_id],
  );
  const found = calls.data?.[0] ?? null;

  useEffect(() => {
    if (found) setResult(found.connected ? "연결" : "미연결");
  }, [found]);

  // 목록에서 펼친 통화의 전사. 안 고르면 카드에 저장된 것(확정분)을 보여준다.
  // **메모에 자동으로 넣지 않는다** — 무엇을 남길지는 조교가 정한다(2026-08-12).
  const [openCall, setOpenCall] = useState<string | null>(null);
  const talk = useApi(
    async () =>
      (
        await http.get<CounselTranscript>(
          `/admin/counseling/${card.counsel_id}/transcript`,
          { params: openCall ? { user_chat_id: openCall } : {} },
        )
      ).data,
    [card.counsel_id, openCall],
  );

  // 시도 횟수는 조교가 넣는다 — 화면이 보여준 통화 목록과 어긋나지 않게.
  const [attempts, setAttempts] = useState(card.attempts);

  const record = useApiAction(async () => {
    const { data } = await http.patch<CounselRecordResult>(`/admin/counseling/${card.counsel_id}`, {
      result,
      absence_reason: result === "연결" ? reason : "",
      call_memo: memo,
      follow_up_action: result === "연결" ? followUp : "",
      makeup_requested: result === "연결" ? makeupRequested : false,
      attempts,
      provider_ref: openCall ?? found?.user_chat_id ?? "",
    });
    return data;
  });

  const submit = async () => {
    const data = await record.run();
    if (!data) return;
    const name = card.student.name ?? "학생";
    if (data.closed) {
      onDone(`${name} ${card.target} 통화 ${data.attempts}회 — 종결`);
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
      aside={`원번 ${card.student.login_id ?? card.student.matching_key} · ${shortDate(card.absence_date)} 결석 · 지금까지 ${card.attempts}회 시도`}
    >
      <div className="ui-stack ui-stack--md ops-form" ref={anchor}>
        {record.error && <Alert tone="danger">{record.error}</Alert>}

        {/* 아래 Field 들과 같은 위계의 칸이다 — 라벨 조판도 같은 것을 쓴다.
            툴바 라벨(11px 대문자 자간)이었을 때는 같은 폼 안에서 이 칸만
            다른 크기·색으로 떠 위계가 하나 더 있는 것처럼 읽혔다. */}
        {(calls.data?.length ?? 0) > 0 && (
          <div className="ui-field">
            <span className="ui-field__label">채널톡 통화 기록</span>
            <div className="ui-stack ui-stack--sm">
              {calls.data?.map((c) => (
                <Button
                  key={c.user_chat_id ?? c.called_at ?? ""}
                  size="sm"
                  variant={openCall === c.user_chat_id ? "primary" : "ghost"}
                  onClick={() => setOpenCall(openCall === c.user_chat_id ? null : c.user_chat_id)}
                >
                  {`${stamp(c.called_at ?? "")} · ${c.connected ? "받음" : "안 받음"}`}
                </Button>
              ))}
            </div>
          </div>
        )}

        {(talk.data?.transcript || talk.data?.recording_url) && (
          <div className="ui-field">
            <span className="ui-field__label">통화 내용</span>
            <div className="ui-stack ui-stack--sm">
              {talk.data?.recording_url && (
                <a href={talk.data.recording_url} target="_blank" rel="noreferrer">
                  녹음 듣기
                </a>
              )}
              {talk.data?.transcript && (
                <pre className="ops-sub" style={{ whiteSpace: "pre-wrap", margin: 0 }}>
                  {talk.data.transcript}
                </pre>
              )}
            </div>
          </div>
        )}

        {found && (
          <Alert tone="info">
            {`채널톡 통화 기록을 찾았습니다 — ${found.connected ? "연결됨" : "받지 않음"}`}
          </Alert>
        )}

        <div className="ui-field">
          <span className="ui-field__label">통화 결과</span>
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
            <Radio
              name={`call-${card.counsel_id}`}
              label="그만 겁니다"
              checked={result === "종결"}
              onChange={() => setResult("종결")}
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

        <div className="ui-field">
          <span className="ui-field__label">시도 횟수</span>
          <div className="ui-row">
            <Button size="sm" onClick={() => setAttempts(Math.max(0, attempts - 1))}>
              −
            </Button>
            <span className="num">{attempts}</span>
            <Button size="sm" onClick={() => setAttempts(attempts + 1)}>
              +
            </Button>
          </div>
        </div>

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

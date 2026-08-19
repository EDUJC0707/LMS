/**
 * /admin/accounts — 계정 일괄 발급 · 등록 전환.
 *
 * API
 *   GET  /api/admin/classes                      반 목록(발급 대상 반 고르기)
 *   POST /api/admin/accounts/bulk                {class_id, rows} → 행별 결과(초기 비번 1회)
 *   POST /api/admin/accounts/{student_id}/register  1주차 출석 확인 후 등록 전환
 *   GET  /api/admin/students?enrollment_status=예비등록  전환 대기 명부(직원 공통 권한)
 *   GET  /api/admin/attendance/sessions(/{id})   판단 근거가 되는 1주차 출석부(출결입력 권한)
 *
 * 화면 설계
 * - 명단은 엑셀에서 그대로 붙여넣는 게 현실이라 “붙여넣기 → 행 격자”가 기본이고,
 *   한두 명만 추가할 때를 위해 행을 직접 채울 수도 있다.
 * - **붙여넣은 표의 열은 조교가 지정한다**(FLOW 2-1·2-2, paste.ts). 파일은 학원이
 *   주는 것이라 열 순서가 매번 다르고, 고정 순서로 자르면 학교명이 폰 칸에 들어가
 *   그 값으로 아이디가 만들어진다 — 조용히 틀리고 되돌릴 수 없다.
 * - **반은 격자 밖에 있다**(FLOW 2-1). 파일에는 어느 반인지가 없고 조교가 고르는
 *   것이라, 행마다 받지 않고 명단 전체에 하나를 건다. 안 고르면 발급하지 않는다.
 * - 이미 계정이 있는 학생은 그 반 수강만 추가되고 아이디·비밀번호가 다시 나오지
 *   않는다(FLOW 2-4) — 결과 표에 `기존` 으로 뜬다.
 * - **번호가 하나만 맞는 행은 `확인필요` 로 세워 둔다**(FLOW 2-3). 그 행은 계정도
 *   수강도 만들어지지 않았고, 결과 표에 겹치는 학생의 값이 실려 온다. 조교가
 *   `같은 사람` 이나 `새로 발급` 을 고르면 그 행만 답을 달아 다시 보낸다 —
 *   대기 상태를 서버에 남기지 않으므로 반쪽 계정이 생길 자리가 없다.
 * - **원번 입력칸은 없다**(2026-07-29 개정). 원번은 이름·휴대폰에서 서버가
 *   계산하는 값이라 입력하면 그 행이 거절된다 — 대신 발급 결과 표에 실려 온다.
 *   학년은 원번의 재료가 아니므로(재개정) 비어 있어도 행이 통과한다.
 * - 전환 대기 목록은 **명부 API 가 기준**이다(예비등록으로 직접 조회). 출결 권한이
 *   있으면 그 위에 1주차 출석 여부를 얹어 판단 근거와 버튼을 같은 줄에 둔다 —
 *   출결 권한이 없어도 목록 자체는 비지 않는다.
 */
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { http, useApi, useApiAction } from "../../../api";
import { useMe } from "../../../auth";
import {
  Alert,
  Badge,
  Button,
  Card,
  DetailsPanel,
  EmptyState,
  ErrorState,
  Field,
  Input,
  Loading,
  Select,
  StatusBadge,
  Table,
  Textarea,
  useToast,
} from "../../../components";
import {
  DirectoryPage,
  PreRegisteredRow,
  directoryParams,
  mergePreRegistered,
} from "./directory";
import "./manage.css";
import { StudentPicker } from "./StudentPicker";
import {
  ColumnChoice,
  EntryField,
  PastedTable,
  assignColumn,
  isMapped,
  readPasted,
  toEntries,
} from "./paste";
import type { BulkResult, BulkResultRow, ClassList, SessionDetail, SessionRow } from "./types";

interface EntryRow {
  key: number;
  name: string;
  phone: string;
  parent_phone: string;
  grade: string;
  school: string;
}

/** 조교의 답이 붙을 수 있는 발급 행 — 서버는 둘 중 하나만 본다(FLOW 2-3). */
type BulkRow = Omit<EntryRow, "key"> & {
  same_as_student_id?: number;
  force_new?: boolean;
};

/** 붙여넣은 표 + 원문 — 원문이 바뀌면 열 지정도 다시 읽는다. */
interface PasteState extends PastedTable {
  text: string;
}

const emptyPaste = (): PasteState => ({ text: "", ...readPasted("") });

let nextKey = 1;
const blankRow = (): EntryRow => ({
  key: nextKey++,
  name: "",
  phone: "",
  parent_phone: "",
  grade: "",
  school: "",
});

const COLUMNS: { field: EntryField; label: string; placeholder: string }[] = [
  { field: "name", label: "이름", placeholder: "홍길동" },
  { field: "phone", label: "학생 휴대폰", placeholder: "01012345678" },
  { field: "parent_phone", label: "학부모 휴대폰", placeholder: "01087654321" },
  { field: "grade", label: "학년", placeholder: "고2" },
  { field: "school", label: "학교", placeholder: "세화고" },
];

/**
 * 서버가 돌려주는 행 실패 사유 중 DB 필드 이름이 섞인 두 개만 현장 말로 바꾼다.
 * (backend/apps/accounts/provisioning.py 의 RowError 문구 — 나머지는 그대로 통과)
 */
const ROW_ERROR_KO: Record<string, string> = {
  "name이 필요합니다.": "이름을 적어야 합니다.",
  "phone 또는 parent_phone이 필요합니다.":
    "학생 휴대폰이나 학부모 휴대폰 중 하나는 있어야 합니다.",
};

const STATUS_TONE: Record<BulkResultRow["status"], "success" | "neutral" | "warning" | "danger"> = {
  생성: "success",
  기존: "neutral",
  확인필요: "warning",
  실패: "danger",
};

/** 결과 표 머리의 집계 — 답을 단 행이 바뀌므로 서버 summary 가 아니라 행에서 센다. */
function countRows(rows: BulkResultRow[]): string {
  const count = (fn: (row: BulkResultRow) => boolean) => rows.filter(fn).length;
  const parts = [
    `생성 ${count((r) => r.status === "생성")}명`,
    `기존 ${count((r) => r.status === "기존")}명`,
    `확인필요 ${count((r) => r.status === "확인필요")}명`,
    `실패 ${count((r) => r.status === "실패")}명`,
    `학부모 신규 ${count((r) => Boolean(r.parent?.created))}명`,
    `기존 연결 ${count((r) => Boolean(r.parent) && !r.parent?.created)}명`,
  ];
  return parts.join(" · ");
}

export default function AccountsPage() {
  const { hasFeature } = useMe();
  const toast = useToast();

  const [rows, setRows] = useState<EntryRow[]>(() => [blankRow(), blankRow(), blankRow()]);
  const [classId, setClassId] = useState("");
  const [paste, setPaste] = useState<PasteState>(emptyPaste);
  const [result, setResult] = useState<BulkResult | null>(null);
  // 확인필요 행에 답을 달아 다시 보내려면 그 행이 무엇이었는지가 있어야 한다.
  const [submitted, setSubmitted] = useState<BulkRow[]>([]);
  const [answering, setAnswering] = useState<number | null>(null);
  // 발급에 성공할 때마다 올린다 — 아래 전환 대기 명부가 새 학생을 바로 집어 온다.
  const [issuedCount, setIssuedCount] = useState(0);

  const classes = useApi(async () => {
    const { data } = await http.get<ClassList>("/admin/classes");
    return data.courses.flatMap((course) => course.classes);
  }, []);

  const issue = useApiAction(async (body: { class_id: number; rows: BulkRow[] }) => {
    const { data } = await http.post<BulkResult>("/admin/accounts/bulk", body);
    return data;
  });

  const filled = rows.filter((row) => row.name.trim() || row.phone.trim() || row.parent_phone.trim());

  const update = (key: number, field: keyof Omit<EntryRow, "key">, value: string) =>
    setRows((prev) => prev.map((row) => (row.key === key ? { ...row, [field]: value } : row)));

  const submit = async () => {
    if (filled.length === 0 || !classId) return;
    const payload: BulkRow[] = filled.map(({ key: _key, ...rest }) => rest);
    const data = await issue.run({ class_id: Number(classId), rows: payload });
    if (!data) return;
    setResult(data);
    setSubmitted(payload);
    if (data.summary.created > 0) setIssuedCount((prev) => prev + 1);
    // 성공한 행은 입력 격자에서 비운다 — 두 번 발급하는 사고를 막는다.
    const failedIndexes = new Set(
      data.results.filter((r) => r.status === "실패").map((r) => r.index),
    );
    const remaining = filled.filter((_, index) => failedIndexes.has(index));
    setRows(remaining.length > 0 ? remaining : [blankRow(), blankRow(), blankRow()]);
  };

  /** 확인필요 행의 답 — 그 행 하나만 다시 보내고 결과 표의 같은 자리를 갈아 끼운다. */
  const answer = async (row: BulkResultRow, choice: Pick<BulkRow, "same_as_student_id" | "force_new">) => {
    const original = submitted[row.index];
    if (!original || !classId) return;
    setAnswering(row.index);
    const data = await issue.run({
      class_id: Number(classId),
      rows: [{ ...original, ...choice }],
    });
    setAnswering(null);
    if (!data) return;
    const answered = { ...data.results[0], index: row.index };
    setResult((prev) =>
      prev
        ? { ...prev, results: prev.results.map((r) => (r.index === row.index ? answered : r)) }
        : prev,
    );
    if (answered.status === "생성" || answered.status === "기존") {
      setIssuedCount((prev) => prev + 1);
    }
  };

  const copySecrets = async () => {
    if (!result) return;
    const lines = result.results
      .filter((row) => row.status === "생성")
      .map((row) =>
        [
          row.name ?? "",
          row.matching_key ?? "",
          row.login_id ?? "",
          row.initial_password ?? "",
        ].join("\t"),
      );
    if (lines.length === 0) return;
    try {
      await navigator.clipboard.writeText(
        `이름\t대조키\t아이디\t초기 비밀번호\n${lines.join("\n")}`,
      );
      toast.show(`${lines.length}명의 아이디·초기 비밀번호를 복사했습니다.`);
    } catch {
      toast.error("복사에 실패했습니다. 표에서 직접 선택해 복사해 주세요.");
    }
  };

  return (
    <div className="ui-stack">
      <Card
        title="새 학생 명단"
        aside={filled.length > 0 ? `입력 ${filled.length}명` : undefined}
        actions={
          <>
            <Button onClick={() => setRows((prev) => [...prev, blankRow()])}>행 추가</Button>
            <Button
              variant="primary"
              loading={issue.pending}
              disabled={!classId}
              onClick={() => void submit()}
            >
              {filled.length > 0 ? `${filled.length}명 계정 발급` : "계정 발급"}
            </Button>
          </>
        }
      >
        <div className="ui-stack ui-stack--md">
          {issue.error && <Alert tone="danger">{issue.error}</Alert>}
          {classes.error && <Alert tone="danger">{classes.error}</Alert>}

          <div className="pm-toolbar">
            <div className="pm-toolbar__wide">
              <Field label="반" required>
                {(props) => (
                  <Select
                    {...props}
                    value={classId}
                    onChange={(e) => setClassId(e.target.value)}
                  >
                    <option value="">선택</option>
                    {(classes.data ?? []).map((klass) => (
                      <option key={klass.class_id} value={klass.class_id}>
                        {klass.course_name} · {klass.name}
                      </option>
                    ))}
                  </Select>
                )}
              </Field>
            </div>
          </div>

          {/* 머리줄과 입력 행은 한 격자다 — 행 간격을 칸 간격(8px)과 맞춰야
              세로도 가로도 같은 눈금으로 읽힌다. */}
          <div className="ui-stack ui-stack--sm">
            <div className="pm-entry" aria-hidden="true">
              {COLUMNS.map((column) => (
                <span key={column.field} className="pm-entry__head">
                  {column.label}
                </span>
              ))}
              <span className="pm-entry__head" />
            </div>

            {rows.map((row, index) => (
              <div className="pm-entry" key={row.key}>
                {COLUMNS.map((column) => (
                  <Input
                    key={column.field}
                    value={row[column.field]}
                    onChange={(e) => update(row.key, column.field, e.target.value)}
                    placeholder={column.placeholder}
                    aria-label={`${index + 1}번째 학생 ${column.label}`}
                    autoComplete="off"
                  />
                ))}
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() =>
                    setRows((prev) =>
                      prev.length === 1 ? [blankRow()] : prev.filter((r) => r.key !== row.key),
                    )
                  }
                  aria-label={`${index + 1}번째 행 비우기`}
                >
                  삭제
                </Button>
              </div>
            ))}
          </div>

          <DetailsPanel summary="엑셀에서 붙여넣기" aside="한 줄에 한 명">
            <div className="ui-stack ui-stack--sm">
              <Textarea
                rows={6}
                aria-label="붙여넣기"
                value={paste.text}
                onChange={(e) => setPaste({ text: e.target.value, ...readPasted(e.target.value) })}
              />

              {paste.cells.length > 0 && <PasteColumns paste={paste} onChange={setPaste} />}

              <div className="ui-row">
                <Button
                  disabled={!isMapped(paste.mapping)}
                  onClick={() => {
                    const entries = toEntries(paste);
                    if (entries.length === 0) return;
                    setRows(entries.map((entry) => ({ ...blankRow(), ...entry })));
                    setPaste(emptyPaste());
                  }}
                >
                  위 격자로 옮기기
                </Button>
                <Button variant="ghost" onClick={() => setPaste(emptyPaste())}>
                  지우기
                </Button>
              </div>
            </div>
          </DetailsPanel>
        </div>
      </Card>

      {result && (
        <Card
          title="발급 결과"
          aside={countRows(result.results)}
          actions={
            <>
              <Button onClick={() => void copySecrets()}>아이디·비밀번호 복사</Button>
              <Button variant="ghost" onClick={() => setResult(null)}>
                결과 닫기
              </Button>
            </>
          }
          padding="none"
        >
          <div className="pm-cardpad">
            <Alert tone="warning">초기 비밀번호는 이 화면에서만 보입니다</Alert>
          </div>
          <Table<BulkResultRow>
            rows={result.results}
            rowKey={(row) => row.index}
            dense
            caption="일괄 발급 행별 결과"
            empty="발급을 시도한 행이 없습니다"
            columns={[
              {
                key: "index",
                header: "행",
                numeric: true,
                width: "3.5rem",
                cell: (row) => row.index + 1,
              },
              {
                key: "name",
                header: "이름",
                // 고치는 자리는 학생 상세다(FLOW 2-6) — 발급 직후가 오타를 보는 자리다.
                cell: (row) =>
                  row.student_id ? (
                    <Link to={`/admin/students/${row.student_id}`}>{row.name ?? "—"}</Link>
                  ) : (
                    (row.name ?? "—")
                  ),
              },
              {
                key: "status",
                header: "결과",
                width: "6rem",
                cell: (row) => <Badge tone={STATUS_TONE[row.status]}>{row.status}</Badge>,
              },
              {
                key: "matching_key",
                header: "대조키",
                cell: (row) => row.matching_key ?? "—",
              },
              {
                key: "login_id",
                header: "학생 아이디",
                numeric: true,
                cell: (row) => row.login_id ?? "—",
              },
              {
                key: "password",
                header: "초기 비밀번호",
                cell: (row) =>
                  row.initial_password ? (
                    <span className="pm-secret">{row.initial_password}</span>
                  ) : (
                    "—"
                  ),
              },
              {
                key: "parent",
                header: "학부모",
                cell: (row) => {
                  if (row.status !== "생성") return "—";
                  if (!row.parent) return "연결 안 함";
                  if (row.parent.created) {
                    return (
                      <>
                        새 계정 <span className="num">{row.parent.login_id}</span>{" "}
                        {row.parent.initial_password && (
                          <span className="pm-secret">{row.parent.initial_password}</span>
                        )}
                      </>
                    );
                  }
                  return (
                    <>
                      기존 계정에 자녀 추가 <span className="num">{row.parent.login_id ?? ""}</span>
                    </>
                  );
                },
              },
              {
                key: "matched",
                header: "겹치는 학생",
                cell: (row) =>
                  row.matched?.length ? (
                    <div className="ui-stack ui-stack--sm">
                      {row.matched.map((match) => (
                        <div className="ui-row" key={match.student_id}>
                          <span>{match.name}</span>
                          <span className="num">{match.login_id}</span>
                          <span className="num">{match.phone || "—"}</span>
                          <span className="num">{match.parent_phone || "—"}</span>
                          <Button
                            size="sm"
                            loading={answering === row.index}
                            onClick={() =>
                              void answer(row, { same_as_student_id: match.student_id })
                            }
                          >
                            같은 사람
                          </Button>
                        </div>
                      ))}
                      <div className="ui-row">
                        <Button
                          size="sm"
                          variant="secondary"
                          loading={answering === row.index}
                          onClick={() => void answer(row, { force_new: true })}
                        >
                          새로 발급
                        </Button>
                      </div>
                    </div>
                  ) : (
                    ""
                  ),
              },
              {
                key: "error",
                header: "실패 사유",
                cell: (row) =>
                  row.error ? (
                    <span className="pm-rowerror">{ROW_ERROR_KO[row.error] ?? row.error}</span>
                  ) : (
                    ""
                  ),
              },
            ]}
          />
        </Card>
      )}

      <PreRegisteredPanel canReadRoster={hasFeature("출결입력")} reloadToken={issuedCount} />

      <FindStudentPanel />
    </div>
  );
}

/* ── 학생 찾기 ─────────────────────────────────────────────────────── */

/**
 * 이미 등록된 학생을 고쳐야 할 때 들어가는 문(FLOW 2-6). 위 두 표는 방금 발급한
 * 행과 전환 대기 학생만 들고 있어서, 지난 달에 등록한 학생은 여기서 찾는다.
 */
function FindStudentPanel() {
  const navigate = useNavigate();
  return (
    <Card title="학생 찾기">
      <StudentPicker
        value={null}
        onChange={(student) => {
          if (student) navigate(`/admin/students/${student.student_id}`);
        }}
      />
    </Card>
  );
}

/* ── 붙여넣은 표의 열 지정 ──────────────────────────────────────────── */

/** 미리 보기 줄 수 — 열이 맞았는지는 몇 줄만 봐도 안다. */
const PREVIEW_ROWS = 3;

function PasteColumns({
  paste,
  onChange,
}: {
  paste: PasteState;
  onChange: (next: PasteState) => void;
}) {
  const body = paste.headerRow ? paste.cells.slice(1) : paste.cells;
  return (
    <div className="pm-paste">
      <table>
        <thead>
          <tr>
            {paste.mapping.map((choice, index) => (
              <th key={index}>
                <Select
                  value={choice}
                  aria-label={`${index + 1}번째 열`}
                  onChange={(e) =>
                    onChange({
                      ...paste,
                      mapping: assignColumn(
                        paste.mapping,
                        index,
                        e.target.value as ColumnChoice,
                      ),
                    })
                  }
                >
                  <option value="">선택</option>
                  {COLUMNS.map((column) => (
                    <option key={column.field} value={column.field}>
                      {column.label}
                    </option>
                  ))}
                </Select>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {body.slice(0, PREVIEW_ROWS).map((row, index) => (
            <tr key={index}>
              {paste.mapping.map((_, column) => (
                <td key={column}>{row[column] ?? ""}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ── 예비등록 → 등록 전환 ───────────────────────────────────────────── */

function PreRegisteredPanel({
  canReadRoster,
  reloadToken,
}: {
  /** 출결입력 권한 — 있으면 1주차 출석 여부를 함께 보여 준다. */
  canReadRoster: boolean;
  /** 계정 발급이 성공할 때마다 바뀌는 값. 바뀌면 명부를 다시 읽는다. */
  reloadToken: number;
}) {
  const [sessionId, setSessionId] = useState<number | null>(null);
  const [pendingId, setPendingId] = useState<number | null>(null);

  // 전환 대기 명부 — 이 화면의 기준. 출결 권한과 무관하게 언제나 읽힌다.
  const waiting = useApi(async () => {
    const { data } = await http.get<DirectoryPage>("/admin/students", {
      params: directoryParams({ enrollment_status: "예비등록" }),
    });
    return data;
  }, [reloadToken]);

  const sessions = useApi(async () => {
    if (!canReadRoster) return null;
    const { data } = await http.get<{ sessions: SessionRow[] }>("/admin/attendance/sessions");
    return data.sessions;
  }, [canReadRoster]);

  // 정책상 근거가 되는 회차는 1주차다 — 없으면 가장 이른 회차.
  const defaultSession = useMemo(() => {
    const list = sessions.data ?? [];
    if (list.length === 0) return null;
    return (list.find((s) => s.week_no === 1) ?? list[0]).session_id;
  }, [sessions.data]);

  const chosen = sessionId ?? defaultSession;

  const roster = useApi(async () => {
    if (!canReadRoster || chosen === null) return null;
    const { data } = await http.get<SessionDetail>(`/admin/attendance/sessions/${chosen}`);
    return data.students;
  }, [canReadRoster, chosen]);

  // 액션이 값을 돌려줘야 성공/실패를 구분할 수 있다(useApiAction 계약).
  const register = useApiAction(async (studentId: number) => {
    await http.post(`/admin/accounts/${studentId}/register`);
    return true;
  });

  const convert = async (student: PreRegisteredRow) => {
    setPendingId(student.student_id);
    const ok = await register.run(student.student_id);
    setPendingId(null);
    if (!ok) return; // 실패 사유는 카드 안 Alert 로 보인다
    await waiting.reload();
  };

  const rows = mergePreRegistered(waiting.data?.results ?? [], roster.data);

  // 표 위에 얹는 줄. 셋 다 없을 수 있어(권한 있음 + 회차 없음 + 오류 없음)
  // 미리 만들어 두고, 있을 때만 여백 있는 칸을 세운다 — 빈 칸이 표를 밀어내지 않게.
  const above = !canReadRoster ? (
    <Alert tone="info">출결 입력 권한이 없어 출석 여부를 함께 볼 수 없습니다</Alert>
  ) : sessions.error ? (
    <Alert tone="danger">{sessions.error}</Alert>
  ) : (sessions.data ?? []).length > 0 ? (
    <div className="pm-toolbar">
      <div className="pm-toolbar__wide">
        <Field label="출석을 확인할 회차">
          {(props) => (
            <Select
              {...props}
              value={chosen ?? ""}
              onChange={(e) => setSessionId(Number(e.target.value))}
            >
              {(sessions.data ?? []).map((session) => (
                <option key={session.session_id} value={session.session_id}>
                  {session.session_date}
                  {session.session_no ? ` · ${session.session_no}회차` : ""}
                  {session.week_no ? ` (${session.week_no}주차)` : ""}
                </option>
              ))}
            </Select>
          )}
        </Field>
      </div>
    </div>
  ) : null;

  return (
    <Card
      title="등록 전환 대기"
      aside={waiting.data ? `예비등록 ${waiting.data.count}명` : undefined}
      padding="none"
    >
      {/* 시험·성적 화면과 같은 규격(.pm-cardpad)으로 얹는다 — 예전에는 아래
          여백이 0 이라 회차 선택 상자가 표 머리에 붙어 있었다. */}
      {(register.error || above) && (
        <div className="pm-cardpad ui-stack ui-stack--md">
          {register.error && (
            <Alert tone="danger" onClose={register.clearError}>
              {register.error}
            </Alert>
          )}
          {above}
        </div>
      )}

      {waiting.loading ? (
        <Loading label="전환 대기 명부를 불러오는 중…" />
      ) : waiting.error ? (
        <ErrorState description={waiting.error} onRetry={waiting.reload} />
      ) : (
        <Table<PreRegisteredRow>
          rows={rows}
          rowKey={(row) => row.student_id}
          dense
          caption="예비등록 학생과 1주차 출석 여부"
          empty={
            <EmptyState title="등록 전환을 기다리는 학생이 없습니다" />
          }
          columns={[
            {
              key: "name",
              header: "학생",
              cell: (row) => (
                <Link to={`/admin/students/${row.student_id}`}>{row.name ?? "이름 미등록"}</Link>
              ),
            },
            {
              key: "login_id",
              header: "원번",
              sortValue: (row) => row.login_id ?? "",
              cell: (row) => row.login_id || "—",
            },
            { key: "grade", header: "학년", cell: (row) => row.grade || "—" },
            { key: "class", header: "반", cell: (row) => row.current_class ?? "미배정" },
            ...(canReadRoster
              ? [
                  {
                    key: "attendance",
                    header: "이 회차 출석",
                    cell: (row: PreRegisteredRow) =>
                      row.attendance_status ? (
                        <StatusBadge status={row.attendance_status} />
                      ) : (
                        <span style={{ color: "var(--color-muted)" }}>기록 없음</span>
                      ),
                  },
                ]
              : []),
            {
              key: "action",
              header: "처리",
              align: "right",
              width: "9rem",
              cell: (row) => (
                <Button
                  size="sm"
                  variant={row.attendance_status === "출석" ? "primary" : "secondary"}
                  loading={pendingId === row.student_id}
                  onClick={() => void convert(row)}
                >
                  등록으로 전환
                </Button>
              ),
            },
          ]}
        />
      )}
    </Card>
  );
}

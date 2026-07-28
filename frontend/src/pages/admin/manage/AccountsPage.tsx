/**
 * /admin/accounts — 계정 일괄 발급 · 등록 전환.
 *
 * API
 *   POST /api/admin/accounts/bulk                명단 리스트 → 행별 결과(초기 비번 1회)
 *   POST /api/admin/accounts/{student_id}/register  1주차 출석 확인 후 등록 전환
 *   GET  /api/admin/attendance/sessions           예비등록 명단을 뽑을 회차 목록
 *   GET  /api/admin/attendance/sessions/{id}      회차 출석부(enrollment_status 포함)
 *
 * 화면 설계
 * - 명단은 엑셀에서 그대로 붙여넣는 게 현실이라 “붙여넣기 → 행 격자”가 기본이고,
 *   한두 명만 추가할 때를 위해 행을 직접 채울 수도 있다.
 * - 등록 전환 대상(예비등록 학생)만 뽑아 주는 API 가 없다. 대신 정책이 곧
 *   “1주차 출석 확인 후 전환”이므로 출결 회차의 출석부에서 예비등록만 걸러
 *   출석 여부와 나란히 보여 준다 — 판단 근거와 버튼이 같은 줄에 있게 된다.
 */
import { useMemo, useState } from "react";

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
  PageHeader,
  Select,
  StatusBadge,
  Table,
  Textarea,
  useToast,
} from "../../../components";
import "./manage.css";
import type {
  BulkResult,
  BulkResultRow,
  RosterStudent,
  SessionDetail,
  SessionRow,
} from "./types";

interface EntryRow {
  key: number;
  name: string;
  phone: string;
  parent_phone: string;
  unique_id: string;
  grade: string;
  school: string;
}

let nextKey = 1;
const blankRow = (): EntryRow => ({
  key: nextKey++,
  name: "",
  phone: "",
  parent_phone: "",
  unique_id: "",
  grade: "",
  school: "",
});

const COLUMNS: { field: keyof Omit<EntryRow, "key">; label: string; placeholder: string }[] = [
  { field: "name", label: "이름", placeholder: "홍길동" },
  { field: "phone", label: "학생 휴대폰", placeholder: "01012345678" },
  { field: "parent_phone", label: "학부모 휴대폰", placeholder: "01087654321" },
  { field: "unique_id", label: "원번", placeholder: "26901" },
  { field: "grade", label: "학년", placeholder: "고2" },
  { field: "school", label: "학교", placeholder: "세화고" },
];

/**
 * 서버가 돌려주는 행 실패 사유 중 DB 필드 이름이 섞인 두 개만 학원 말로 바꾼다.
 * (backend/apps/accounts/provisioning.py 의 RowError 문구 — 나머지는 그대로 통과)
 */
const ROW_ERROR_KO: Record<string, string> = {
  "name이 필요합니다.": "이름을 적어야 합니다.",
  "phone 또는 parent_phone이 필요합니다.":
    "학생 휴대폰이나 학부모 휴대폰 중 하나는 있어야 합니다.",
};

/** 엑셀·메모장에서 복사한 덩어리를 행으로 쪼갠다(탭·쉼표 모두 허용). */
function parsePasted(text: string): EntryRow[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
    .map((line) => {
      const cells = line.split(/\t|,/).map((cell) => cell.trim());
      const [name = "", phone = "", parentPhone = "", uniqueId = "", grade = "", school = ""] =
        cells;
      return {
        ...blankRow(),
        name,
        phone,
        parent_phone: parentPhone,
        unique_id: uniqueId,
        grade,
        school,
      };
    });
}

export default function AccountsPage() {
  const { hasFeature } = useMe();
  const toast = useToast();

  const [rows, setRows] = useState<EntryRow[]>(() => [blankRow(), blankRow(), blankRow()]);
  const [pasted, setPasted] = useState("");
  const [result, setResult] = useState<BulkResult | null>(null);

  const issue = useApiAction(async (body: Omit<EntryRow, "key">[]) => {
    const { data } = await http.post<BulkResult>("/admin/accounts/bulk", body);
    return data;
  });

  const filled = rows.filter((row) => row.name.trim() || row.phone.trim() || row.parent_phone.trim());

  const update = (key: number, field: keyof Omit<EntryRow, "key">, value: string) =>
    setRows((prev) => prev.map((row) => (row.key === key ? { ...row, [field]: value } : row)));

  const submit = async () => {
    if (filled.length === 0) return;
    const payload = filled.map(({ key: _key, ...rest }) => rest);
    const data = await issue.run(payload);
    if (!data) return;
    setResult(data);
    // 성공한 행은 입력 격자에서 비운다 — 두 번 발급하는 사고를 막는다.
    const failedIndexes = new Set(
      data.results.filter((r) => r.status === "실패").map((r) => r.index),
    );
    const remaining = filled.filter((_, index) => failedIndexes.has(index));
    setRows(remaining.length > 0 ? remaining : [blankRow(), blankRow(), blankRow()]);
  };

  const copySecrets = async () => {
    if (!result) return;
    const lines = result.results
      .filter((row) => row.status === "생성")
      .map((row) =>
        [row.name ?? "", row.login_id ?? "", row.initial_password ?? ""].join("\t"),
      );
    if (lines.length === 0) return;
    try {
      await navigator.clipboard.writeText(`이름\t아이디\t초기 비밀번호\n${lines.join("\n")}`);
      toast.show(`${lines.length}명의 아이디·초기 비밀번호를 복사했습니다.`);
    } catch {
      toast.error("복사에 실패했습니다. 표에서 직접 선택해 복사해 주세요.");
    }
  };

  return (
    <>
      <PageHeader
        title="계정 발급"
        description="새 학생 명단을 넣어 학생·학부모 계정을 한 번에 만듭니다. 1주차 출석을 확인한 학생은 아래에서 등록으로 바꿉니다."
      />

      <Card
        title="새 학생 명단"
        aside={filled.length > 0 ? `입력 ${filled.length}명` : undefined}
        actions={
          <>
            <Button onClick={() => setRows((prev) => [...prev, blankRow()])}>행 추가</Button>
            <Button variant="primary" loading={issue.pending} onClick={() => void submit()}>
              {filled.length > 0 ? `${filled.length}명 계정 발급` : "계정 발급"}
            </Button>
          </>
        }
      >
        <div className="ui-stack--md">
          {issue.error && <Alert tone="danger">{issue.error}</Alert>}

          <Alert tone="info">
            아이디는 학생 본인 휴대폰 번호입니다. 휴대폰이 없는 학생은 학부모 번호 뒤에 a, b …
            를 붙여 만듭니다. 학부모 번호가 이미 등록돼 있으면 새 계정 대신 자녀만 연결됩니다.
          </Alert>

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

          <DetailsPanel summary="엑셀에서 붙여넣기" aside="한 줄에 한 명">
            <div className="ui-stack--sm">
              <Field
                label="명단 붙여넣기"
                hint="이름 · 학생 휴대폰 · 학부모 휴대폰 · 원번 · 학년 · 학교 순서. 빈 칸은 그냥 비워 두세요."
              >
                {(props) => (
                  <Textarea
                    {...props}
                    rows={6}
                    value={pasted}
                    onChange={(e) => setPasted(e.target.value)}
                    placeholder={"홍길동\t01099990001\t01088880001\t26901\t고2\t세화고"}
                  />
                )}
              </Field>
              <div className="ui-row">
                <Button
                  onClick={() => {
                    const parsed = parsePasted(pasted);
                    if (parsed.length === 0) return;
                    setRows(parsed);
                    setPasted("");
                  }}
                >
                  위 격자로 옮기기
                </Button>
                <Button variant="ghost" onClick={() => setPasted("")}>
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
          aside={`생성 ${result.summary.created}명 · 실패 ${result.summary.failed}명 · 학부모 신규 ${result.summary.parents_created}명 · 기존 연결 ${result.summary.parents_linked}명`}
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
          <div style={{ padding: "var(--space-lg) var(--space-lg) 0" }}>
            <Alert tone="warning">
              초기 비밀번호는 이 화면에서만 보입니다. 지금 복사해 학생·학부모에게 전달하세요.
              알림톡을 연결하면 발급과 동시에 자동 발송으로 바뀝니다.
            </Alert>
          </div>
          <Table<BulkResultRow>
            rows={result.results}
            rowKey={(row) => row.index}
            dense
            caption="일괄 발급 행별 결과"
            empty="발급을 시도한 행이 없습니다."
            columns={[
              {
                key: "index",
                header: "행",
                numeric: true,
                width: "3.5rem",
                cell: (row) => row.index + 1,
              },
              { key: "name", header: "이름", cell: (row) => row.name ?? "—" },
              {
                key: "status",
                header: "결과",
                width: "5rem",
                cell: (row) =>
                  row.status === "생성" ? (
                    <Badge tone="success">생성</Badge>
                  ) : (
                    <Badge tone="danger">실패</Badge>
                  ),
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
                  if (row.status === "실패") return "—";
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
                key: "error",
                header: "실패 사유",
                cell: (row) =>
                  row.error ? (
                    <span style={{ color: "var(--color-danger)" }}>
                      {ROW_ERROR_KO[row.error] ?? row.error}
                    </span>
                  ) : (
                    ""
                  ),
              },
            ]}
          />
        </Card>
      )}

      {hasFeature("출결입력") ? <PreRegisteredPanel /> : <PreRegisteredUnavailable />}
    </>
  );
}

/* ── 예비등록 → 등록 전환 ───────────────────────────────────────────── */

function PreRegisteredPanel() {
  const sessions = useApi(
    () =>
      http.get<{ sessions: SessionRow[] }>("/admin/attendance/sessions").then((r) => r.data.sessions),
    [],
  );
  const [sessionId, setSessionId] = useState<number | null>(null);

  // 정책상 근거가 되는 회차는 1주차다 — 없으면 가장 이른 회차.
  const defaultSession = useMemo(() => {
    const list = sessions.data ?? [];
    if (list.length === 0) return null;
    return (list.find((s) => s.week_no === 1) ?? list[0]).session_id;
  }, [sessions.data]);

  const chosen = sessionId ?? defaultSession;

  const roster = useApi(async () => {
    if (chosen === null) return null;
    const { data } = await http.get<SessionDetail>(`/admin/attendance/sessions/${chosen}`);
    return data;
  }, [chosen]);

  // 액션이 값을 돌려줘야 성공/실패를 구분할 수 있다(useApiAction 계약).
  const register = useApiAction(async (studentId: number) => {
    await http.post(`/admin/accounts/${studentId}/register`);
    return true;
  });
  const [pendingId, setPendingId] = useState<number | null>(null);

  const convert = async (student: RosterStudent) => {
    setPendingId(student.student_id);
    const ok = await register.run(student.student_id);
    setPendingId(null);
    if (!ok) return; // 실패 사유는 카드 안 Alert 로 보인다
    await roster.reload();
  };

  const waiting = (roster.data?.students ?? []).filter(
    (student) => student.enrollment_status === "예비등록",
  );

  return (
    <Card
      title="등록 전환 대기"
      aside={roster.data ? `예비등록 ${waiting.length}명` : undefined}
      padding="none"
    >
      <div style={{ padding: "var(--space-lg) var(--space-lg) 0" }} className="ui-stack--md">
        <p style={{ margin: 0, color: "var(--color-ink-2)" }}>
          계정을 받은 학생은 먼저 예비등록 상태입니다. 실제로 첫 수업에 나온 것을 출석부로
          확인한 뒤 등록으로 바꾸면 성적·클리닉·워크북이 열립니다.
        </p>

        {register.error && (
          <Alert tone="danger" onClose={register.clearError}>
            {register.error}
          </Alert>
        )}

        {sessions.loading ? null : sessions.error ? (
          <Alert tone="danger">{sessions.error}</Alert>
        ) : (
          <div className="pm-toolbar">
            <div className="pm-toolbar__wide">
              <Field label="확인할 회차" hint="보통 1주차 출석부를 기준으로 판단합니다.">
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
        )}
      </div>

      {roster.loading ? (
        <Loading label="출석부를 불러오는 중…" />
      ) : roster.error ? (
        <ErrorState description={roster.error} onRetry={roster.reload} />
      ) : (
        <Table<RosterStudent>
          rows={waiting}
          rowKey={(row) => row.student_id}
          dense
          caption="예비등록 학생과 이 회차 출석 여부"
          empty={
            <EmptyState
              title="이 회차에는 등록 전환을 기다리는 학생이 없습니다"
              description="다른 회차를 고르거나, 위에서 새 명단을 발급하세요."
            />
          }
          columns={[
            { key: "name", header: "학생", cell: (row) => row.name },
            {
              key: "unique_id",
              header: "원번",
              numeric: true,
              sortValue: (row) => row.unique_id,
              cell: (row) => row.unique_id || "—",
            },
            { key: "class", header: "반", cell: (row) => row.current_class ?? "미배정" },
            {
              key: "attendance",
              header: "이 회차 출석",
              cell: (row) =>
                row.attendance?.status ? (
                  <StatusBadge status={row.attendance.status} />
                ) : (
                  <span style={{ color: "var(--color-muted)" }}>기록 없음</span>
                ),
            },
            {
              key: "action",
              header: "처리",
              align: "right",
              width: "9rem",
              cell: (row) => (
                <Button
                  size="sm"
                  variant={row.attendance?.status === "출석" ? "primary" : "secondary"}
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

/** 출결 권한이 없으면 예비등록 명단을 뽑을 길이 없다 — 왜 비었는지 그대로 쓴다. */
function PreRegisteredUnavailable() {
  return (
    <Card title="등록 전환 대기">
      <EmptyState
        title="예비등록 명단은 출석부에서 불러옵니다"
        description="이 계정에는 출결 입력 권한이 없어 출석부를 열 수 없습니다. 출결을 담당하는 관리자에게 전환을 요청하거나, 대표에게 출결입력 권한을 요청하세요."
      />
    </Card>
  );
}

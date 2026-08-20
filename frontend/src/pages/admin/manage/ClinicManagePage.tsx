/**
 * /admin/clinic — 클리닉 대기열 · 배정 · 출결 · 평가.
 *
 * API
 *   GET  /api/admin/clinic/requests?status=&date=
 *   POST /api/admin/clinic/requests/{id}/assign      {assigned_staff_id}
 *   POST /api/admin/clinic/requests/{id}/reject      {reason}
 *   POST /api/admin/clinic/requests/{id}/attendance  {status: "출석"|"결석"}
 *   POST /api/admin/clinic/requests/{id}/evaluation  {items[], overall_result?}
 *   GET  /api/admin/clinic/eval-criteria
 *   POST /api/admin/clinic/students/{id}/unban       (대표 전용)
 *   GET  /api/admin/clinic/capacity                  정원
 *   PUT  /api/admin/clinic/capacity                  {capacity}
 *
 * 화면 설계
 * - 왼쪽 대기열 · 오른쪽 처리판. 신청 하나를 고르면 그 건에 지금 할 수 있는
 *   일만 오른쪽에 나온다(서버 상태 규칙과 1:1).
 *     배정   = 대기 · 승인배정   (재배정 허용)
 *     미승인 = 대기
 *     출결   = 승인배정 & 아직 출결 미기록
 *     평가   = 승인배정
 *     제한해제 = 제한 중 학생 + 대표 계정
 * - 결석은 되돌릴 수 없고 2회면 자동 제한이 걸린다. 노쇼 1회인 학생에게는
 *   결석 버튼 위에 경고를 먼저 띄운다.
 * - **정원은 클리닉 조교 수다**(FLOW 3-7). 한 타임에 몇 명을 받는가라 시간마다
 *   다를 이유가 없어 숫자 하나이고, 고치면 살아 있는 슬롯 전부에 걸린다.
 *   지난 것은 안 건드린다 — 줄여도 이미 잡힌 신청은 그대로다.
 */
import { useMemo, useState } from "react";
import Markdown from "react-markdown";

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
  Radio,
  Select,
  StatusBadge,
  Table,
  Tabs,
} from "../../../components";
import "./manage.css";
import type { ClinicCriteria, ClinicRequestRow, ClinicStatus, StaffMatrix } from "./types";

// `지난` 만 축이 다르다 — 나머지는 상태, 이것은 기간이다. 한 줄에 섞어 두는
// 이유는 관리자가 하는 일이 하나라서다: 목록을 좁혀서 한 건을 고른다.
type TabKey = "전체" | "지난" | ClinicStatus;

// 서버 값집합(ClinicRequest.RejectReason)과 같아야 한다 — 여기 없는 값을
// 보내면 400 이다.
const REJECT_REASONS = ["정원 마감", "시간 불가"];
const TABS: { key: TabKey; label: string }[] = [
  { key: "대기", label: "대기" },
  { key: "승인배정", label: "승인·배정" },
  { key: "미승인", label: "미승인" },
  { key: "취소", label: "취소" },
  { key: "전체", label: "전체" },
  { key: "지난", label: "지난" },
];

export default function ClinicManagePage() {
  const { me, hasRole } = useMe();
  const isOwner = hasRole("대표");

  const [tab, setTab] = useState<TabKey>("대기");
  const [date, setDate] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const queue = useApi(async () => {
    const { data } = await http.get<{ requests: ClinicRequestRow[] }>("/admin/clinic/requests", {
      params: {
        ...(tab === "전체" || tab === "지난" ? {} : { status: tab }),
        ...(tab === "지난" ? { period: "지난" } : {}),
        ...(date ? { date } : {}),
      },
    });
    return data.requests;
  }, [tab, date]);

  const criteria = useApi(
    () =>
      http
        .get<{ criteria: ClinicCriteria[] }>("/admin/clinic/eval-criteria")
        .then((r) => r.data.criteria),
    [],
  );

  // 배정 후보 = 지금 로그인한 직원 + 이미 배정된 적 있는 직원.
  // 대표만 전체 직원 명부(/admin/staff)를 열 수 있으므로 그때만 합친다.
  const staffList = useApi(async () => {
    if (!isOwner) return null;
    const { data } = await http.get<StaffMatrix>("/admin/staff");
    return data.staff.filter((s) => s.is_active);
  }, [isOwner]);

  const rows = queue.data ?? [];
  const selected = rows.find((row) => row.clinic_id === selectedId) ?? null;

  const assignable = useMemo(() => {
    const map = new Map<number, string>();
    if (me && me.role !== "학생" && me.role !== "학부모") map.set(me.user_id, `${me.name} (나)`);
    for (const row of rows) {
      if (row.assigned_staff) map.set(row.assigned_staff.user_id, row.assigned_staff.name);
    }
    for (const staff of staffList.data ?? []) map.set(staff.user_id, `${staff.name} · ${staff.role}`);
    return [...map].map(([user_id, label]) => ({ user_id, label }));
  }, [me, rows, staffList.data]);

  return (
    <div className="ui-stack">
      {/* 상태 탭과 날짜는 같은 일(대기열 좁히기)을 한다 — 한 덩어리로 묶어
          16px 으로 붙이고, 대기열·처리판과는 24px 로 띄운다. */}
      <CapacityCard />

      <div className="ui-stack ui-stack--md">
        <Tabs items={TABS} value={tab} onChange={setTab} label="신청 상태" />

        <div className="pm-toolbar">
          <Field label="날짜">
            {(props) => (
              <Input
                {...props}
                type="date"
                value={date}
                onChange={(e) => setDate(e.target.value)}
              />
            )}
          </Field>
          {date && (
            <Button variant="ghost" onClick={() => setDate("")}>
              날짜 조건 지우기
            </Button>
          )}
        </div>
      </div>

      <div className="pm-split">
        <Card
          title="신청 대기열"
          aside={queue.data ? `${rows.length}건` : undefined}
          padding="none"
        >
          {queue.loading ? (
            <Loading label="신청을 불러오는 중…" />
          ) : queue.error ? (
            <ErrorState description={queue.error} onRetry={queue.reload} />
          ) : (
            <Table<ClinicRequestRow>
              rows={rows}
              rowKey={(row) => row.clinic_id}
              dense
              caption="클리닉 신청 목록"
              onRowClick={(row) => setSelectedId(row.clinic_id)}
              isSelected={(row) => row.clinic_id === selectedId}
              empty={
                <EmptyState
                  title={
                    tab === "전체" || tab === "지난"
                      ? "이 조건에 해당하는 신청이 없습니다"
                      : `${tab} 상태인 신청이 없습니다`
                  }
                />
              }
              columns={[
                {
                  key: "student",
                  header: "학생",
                  sortValue: (row) => row.student.name ?? "",
                  cell: (row) => (
                    <>
                      {row.student.name}{" "}
                      <span className="num pm-none">{row.student.login_id ?? row.student.matching_key}</span>
                      {row.student.clinic_banned && (
                        <>
                          {" "}
                          <Badge tone="danger">신청 제한</Badge>
                        </>
                      )}
                    </>
                  ),
                },
                {
                  key: "when",
                  header: "희망 일시",
                  sortValue: (row) => `${row.requested_date} ${row.requested_time}`,
                  cell: (row) => (
                    <span className="num">
                      {row.requested_date} {row.requested_time}
                    </span>
                  ),
                },
                {
                  key: "status",
                  header: "상태",
                  width: "6rem",
                  cell: (row) => <StatusBadge status={row.status} />,
                },
                {
                  key: "staff",
                  header: "담당",
                  cell: (row) => row.assigned_staff?.name ?? "—",
                },
                {
                  key: "attendance",
                  header: "출결",
                  width: "5rem",
                  cell: (row) =>
                    row.attendance_status ? (
                      <StatusBadge status={row.attendance_status} />
                    ) : (
                      <span className="pm-none">—</span>
                    ),
                },
              ]}
            />
          )}
        </Card>

        <div className="pm-split__side">
          {selected ? (
            <RequestPanel
              key={selected.clinic_id}
              request={selected}
              assignable={assignable}
              criteria={criteria.data ?? []}
              isOwner={isOwner}
              onDone={queue.reload}
            />
          ) : (
            <Card title="처리">
              <EmptyState title="왼쪽에서 신청을 하나 고르세요" />
            </Card>
          )}
        </div>
      </div>

      <DetailsPanel
        summary="조교 평가 기준"
        aside={criteria.data ? `${criteria.data.length}개 항목` : undefined}
      >
        {criteria.error ? (
          <Alert tone="danger">{criteria.error}</Alert>
        ) : (
          <ol className="pm-numlist">
            {(criteria.data ?? []).map((item) => (
              <li key={item.criteria_id}>
                <b>{item.item}</b>
                {item.description && <span> — {item.description}</span>}
              </li>
            ))}
          </ol>
        )}
      </DetailsPanel>
    </div>
  );
}

/* ── 선택한 신청 하나의 처리판 ──────────────────────────────────────── */

/** 정원 — 클리닉 조교 수(FLOW 3-7). 고치면 살아 있는 슬롯 전부에 걸린다. */
function CapacityCard() {
  const [draft, setDraft] = useState<string | null>(null);

  const current = useApi(async () => {
    const { data } = await http.get<{ capacity: number }>("/admin/clinic/capacity");
    return data.capacity;
  }, []);

  const save = useApiAction(async (value: number) => {
    const { data } = await http.put<{ capacity: number }>("/admin/clinic/capacity", {
      capacity: value,
    });
    current.setData(data.capacity);
    setDraft(null);
  });

  if (current.loading) return <Loading label="정원을 불러오는 중…" />;
  if (current.error) return <ErrorState description={current.error} onRetry={current.reload} />;

  const value = draft ?? String(current.data ?? "");
  const parsed = Number(value);
  const dirty = draft !== null && Number.isInteger(parsed) && parsed >= 1;

  return (
    <Card title="정원">
      {save.error && <Alert tone="danger">{save.error}</Alert>}
      <div className="pm-toolbar">
        {/* 카드 제목이 이미 "정원"이라 칸에 라벨을 또 붙이지 않는다. */}
        <Input
          aria-label="정원"
          type="number"
          min={1}
          value={value}
          onChange={(e) => setDraft(e.target.value)}
        />
        {dirty && (
          <Button disabled={save.pending} onClick={() => void save.run(parsed)}>
            저장
          </Button>
        )}
      </div>
    </Card>
  );
}


function RequestPanel({
  request,
  assignable,
  criteria,
  isOwner,
  onDone,
}: {
  request: ClinicRequestRow;
  assignable: { user_id: number; label: string }[];
  criteria: ClinicCriteria[];
  isOwner: boolean;
  onDone: () => Promise<void>;
}) {
  const [staffId, setStaffId] = useState<string>(
    request.assigned_staff
      ? String(request.assigned_staff.user_id)
      : String(assignable[0]?.user_id ?? ""),
  );
  // 빈 칸으로 시작한다 — 서버가 화상 스페이스를 만들기 때문이다. 기존 링크를
  // 채워 두면 재배정할 때마다 그 값이 "직접 입력"으로 되돌아가 서버가 만든
  // 스페이스 참조가 지워진다(backend clinic_admin.assign 순서 1·2).
  const [rejectReason, setRejectReason] = useState("");

  // 모든 액션은 성공 시 true 를 돌려준다 — useApiAction 은 실패에만
  // undefined 를 주므로 void 액션은 성공/실패를 구분할 수 없다.
  const assign = useApiAction(async () => {
    await http.post(`/admin/clinic/requests/${request.clinic_id}/assign`, {
      assigned_staff_id: Number(staffId),
    });
    return true;
  });
  const reject = useApiAction(async () => {
    await http.post(`/admin/clinic/requests/${request.clinic_id}/reject`, {
      reason: rejectReason,
    });
    return true;
  });
  const attend = useApiAction(async (status: "출석" | "결석") => {
    await http.post(`/admin/clinic/requests/${request.clinic_id}/attendance`, { status });
    return true;
  });
  const unban = useApiAction(async () => {
    await http.post(`/admin/clinic/students/${request.student.student_id}/unban`);
    return true;
  });

  const canAssign = request.status === "대기" || request.status === "승인배정";
  const canReject = request.status === "대기";
  const canMarkAttendance = request.status === "승인배정" && request.attendance_status === null;
  const canEvaluate = request.status === "승인배정";
  const assignReady = staffId !== "";

  return (
    <Card
      title={`${request.student.name} 학생 신청`}
      aside={`신청 번호 ${request.clinic_id}`}
    >
      <div className="ui-stack ui-stack--md">
        <dl className="pm-defs">
          <dt>원번</dt>
          <dd className="num">{request.student.login_id ?? request.student.matching_key}</dd>
          <dt>희망 일시</dt>
          <dd className="num">
            {request.requested_date} {request.requested_time}
          </dd>
          <dt>상태</dt>
          <dd>
            <StatusBadge status={request.status} />
            {request.reject_reason && <> {request.reject_reason}</>}
            {request.attendance_status && (
              <>
                {" "}
                <StatusBadge status={request.attendance_status} />
              </>
            )}
          </dd>
          <dt>담당 조교</dt>
          <dd>{request.assigned_staff?.name ?? "아직 없음"}</dd>
          {request.conference_url && (
            <>
              <dt>화상 링크</dt>
              <dd>
                <a href={request.conference_url} target="_blank" rel="noreferrer">
                  {request.conference_url}
                </a>
              </dd>
            </>
          )}
          <dt>노쇼</dt>
          <dd className="num">{request.student.noshow_count}회</dd>
        </dl>

        {request.supervision && (
          <Card title="전사 요약" padding="none">
            <div className="ui-stack ui-stack--sm cl-supervision">
              {request.supervision.summary ? (
                // 업체가 마크다운으로 준다(불릿·굵게, 때로는 표·번호목록).
                // 손으로 파싱하면 오늘 오는 두 가지만 맞고 세 번째에서 깨진다.
                // **raw HTML 은 켜지 않는다** — 학생 발화를 요약한 외부 업체
                // 출력이라 신뢰 입력이 아니다(react-markdown 은 기본이 끔).
                <div className="cl-supervision__body">
                  <Markdown>{request.supervision.summary}</Markdown>
                </div>
              ) : (
                <EmptyState title="요약을 읽지 못했습니다" />
              )}
              <a href={request.supervision.transcript_url} target="_blank" rel="noreferrer">
                전사 원문 열기
              </a>
            </div>
          </Card>
        )}

        {request.student.clinic_banned && (
          <Alert tone="danger">신청 제한 상태</Alert>
        )}

        {request.student.clinic_banned && isOwner && (
          <>
            {unban.error && <Alert tone="danger">{unban.error}</Alert>}
            <Button
              variant="secondary"
              loading={unban.pending}
              onClick={async () => {
                if (await unban.run()) await onDone();
              }}
            >
              신청 제한 풀기
            </Button>
          </>
        )}

        {canAssign && (
          <div className="ui-stack ui-stack--sm pm-actionblock">
            {(assign.error || reject.error) && (
              <Alert tone="danger">{assign.error ?? reject.error}</Alert>
            )}
            <Field label="담당 조교" required>
              {(props) => (
                <Select {...props} value={staffId} onChange={(e) => setStaffId(e.target.value)}>
                  {assignable.length === 0 && <option value="">배정할 직원이 없습니다</option>}
                  {assignable.map((staff) => (
                    <option key={staff.user_id} value={staff.user_id}>
                      {staff.label}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            <div className="ui-row">
              <Button
                variant="primary"
                disabled={!assignReady}
                loading={assign.pending}
                onClick={async () => {
                  if (await assign.run()) await onDone();
                }}
              >
                {request.status === "승인배정" ? "담당·링크 다시 배정" : "승인하고 배정"}
              </Button>
              {canReject && (
                <>
                  <Select
                    value={rejectReason}
                    onChange={(e) => setRejectReason(e.target.value)}
                    aria-label="미승인 사유"
                  >
                    <option value="">미승인 사유</option>
                    {REJECT_REASONS.map((reason) => (
                      <option key={reason} value={reason}>
                        {reason}
                      </option>
                    ))}
                  </Select>
                  <Button
                    variant="ghost"
                    disabled={rejectReason === ""}
                    loading={reject.pending}
                    onClick={async () => {
                      if (await reject.run()) await onDone();
                    }}
                  >
                    미승인 처리
                  </Button>
                </>
              )}
            </div>
          </div>
        )}

        {canMarkAttendance && (
          <div className="ui-stack ui-stack--sm pm-actionblock">
            {attend.error && <Alert tone="danger">{attend.error}</Alert>}
            {request.student.noshow_count >= 1 && (
              <Alert tone="warning">
                노쇼 {request.student.noshow_count}회 — 한 번 더 결석이면 신청이 막힙니다
              </Alert>
            )}
            <div className="ui-row">
              <Button
                variant="primary"
                loading={attend.pending}
                onClick={async () => {
                  if (await attend.run("출석")) await onDone();
                }}
              >
                출석으로 기록
              </Button>
              <Button
                variant="danger"
                loading={attend.pending}
                onClick={async () => {
                  if (await attend.run("결석")) await onDone();
                }}
              >
                결석(노쇼)으로 기록
              </Button>
            </div>
          </div>
        )}

        {canEvaluate && criteria.length > 0 && (
          <EvaluationForm clinicId={request.clinic_id} criteria={criteria} onDone={onDone} />
        )}
      </div>
    </Card>
  );
}

/* ── 조교 수행 평가 ─────────────────────────────────────────────────── */

function EvaluationForm({
  clinicId,
  criteria,
  onDone,
}: {
  clinicId: number;
  criteria: ClinicCriteria[];
  onDone: () => Promise<void>;
}) {
  const [results, setResults] = useState<Record<number, "충족" | "미충족">>({});
  const [overall, setOverall] = useState("");
  const [saved, setSaved] = useState(false);

  const submit = useApiAction(async () => {
    await http.post(`/admin/clinic/requests/${clinicId}/evaluation`, {
      items: Object.entries(results).map(([criteriaId, result]) => ({
        criteria_id: Number(criteriaId),
        result,
      })),
      ...(overall ? { overall_result: overall } : {}),
    });
    return true;
  });

  const answered = Object.keys(results).length;

  return (
    <DetailsPanel
      summary="조교 수행 평가"
      aside={saved ? "저장됨" : `${answered}/${criteria.length} 항목`}
    >
      <div className="ui-stack ui-stack--sm">
        {submit.error && <Alert tone="danger">{submit.error}</Alert>}
        {criteria.map((item) => (
          <fieldset key={item.criteria_id} className="pm-critset">
            <legend>{item.item}</legend>
            <div className="ui-row">
              {(["충족", "미충족"] as const).map((value) => (
                <Radio
                  key={value}
                  name={`crit-${clinicId}-${item.criteria_id}`}
                  label={value}
                  checked={results[item.criteria_id] === value}
                  onChange={() => {
                    setSaved(false);
                    setResults((prev) => ({ ...prev, [item.criteria_id]: value }));
                  }}
                />
              ))}
            </div>
          </fieldset>
        ))}

        <Field label="종합 판정">
          {(props) => (
            <Select
              {...props}
              value={overall}
              onChange={(e) => {
                setSaved(false);
                setOverall(e.target.value);
              }}
            >
              <option value="">아직 판단하지 않음</option>
              <option value="적격">적격</option>
              <option value="부적격">부적격</option>
            </Select>
          )}
        </Field>

        <Button
          variant="primary"
          disabled={answered === 0}
          loading={submit.pending}
          onClick={async () => {
            if (!(await submit.run())) return;
            setSaved(true);
            await onDone();
          }}
        >
          평가 저장
        </Button>
      </div>
    </DetailsPanel>
  );
}

/**
 * 출결 입력 — 회차 명단(핵심 화면).
 *
 * 호출: GET·PUT /api/admin/attendance/sessions/{id}
 *      · GET  /api/admin/makeup-requests            (동보 지급 여부 확인)
 *      · POST /api/admin/makeup-requests/{id}/approve
 *
 * 설계 요지
 * - 집계 바를 상단에 고정한다. 30명을 훑는 동안에도 "몇 명 남았나"가 늘 보인다.
 * - 저장은 **바꾼 행만** 보낸다(부분 upsert). 손대지 않은 행은 건드리지 않는다.
 * - 저장 응답의 triggers 를 문장으로 옮긴다 — 이 시스템의 자동화를 사람이
 *   체감하는 유일한 지점이다.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { http, useApi, useApiAction } from "../../../api";
import { useMe } from "../../../auth";
import {
  Alert,
  Button,
  Card,
  Checkbox,
  ErrorState,
  Loading,
  PageHeader,
  StatusBadge,
  Table,
  useToast,
} from "../../../components";
import type { Column } from "../../../components";
import { Fig } from "./Fig";
import { longDate, sessionLabel, stamp } from "./format";
import "./ops.css";
import type {
  AttendanceEntry,
  AttendanceStatus,
  AttendanceTriggers,
  MakeupRow,
  RosterStudent,
  SessionDetail,
} from "./types";
import { ATTENDANCE_STATUSES } from "./types";

type Draft = { status: AttendanceStatus | ""; examTaken: boolean };
type DraftMap = Record<number, Draft>;

const TONE: Record<AttendanceStatus, "present" | "late" | "absent"> = {
  출석: "present",
  지각: "late",
  결석: "absent",
};

function draftFrom(students: RosterStudent[]): DraftMap {
  const next: DraftMap = {};
  for (const student of students) {
    next[student.student_id] = {
      status: student.attendance?.status ?? "",
      examTaken: student.attendance?.exam_taken === true,
    };
  }
  return next;
}

export default function AttendanceSessionPage() {
  const { sessionId } = useParams();
  const { hasFeature } = useMe();
  const toast = useToast();
  const canMakeup = hasFeature("영상지급관리");

  const detail = useApi(
    async () =>
      (await http.get<SessionDetail>(`/admin/attendance/sessions/${sessionId}`)).data,
    [sessionId],
  );

  const makeups = useApi<MakeupRow[] | null>(
    async () =>
      canMakeup
        ? (await http.get<{ requests: MakeupRow[] }>("/admin/makeup-requests")).data.requests
        : null,
    [canMakeup],
  );

  const [draft, setDraft] = useState<DraftMap>({});
  const [examMode, setExamMode] = useState(false);
  const [blankOnly, setBlankOnly] = useState(false);
  const [saved, setSaved] = useState<AttendanceTriggers | null>(null);

  const students = useMemo(() => detail.data?.students ?? [], [detail.data]);

  useEffect(() => {
    if (!detail.data) return;
    setDraft(draftFrom(detail.data.students));
    // 현장 시험 기록이 하나라도 있으면 시험 열을 켠 채로 연다.
    setExamMode(detail.data.students.some((s) => s.attendance?.exam_taken != null));
  }, [detail.data]);

  const setRow = (studentId: number, patch: Partial<Draft>) =>
    setDraft((prev) => ({
      ...prev,
      [studentId]: { ...(prev[studentId] ?? { status: "", examTaken: false }), ...patch },
    }));

  const live = useMemo(() => {
    const counts = { 출석: 0, 지각: 0, 결석: 0, 미입력: 0 };
    for (const student of students) {
      const status = draft[student.student_id]?.status;
      if (status) counts[status] += 1;
      else counts.미입력 += 1;
    }
    return counts;
  }, [students, draft]);

  const changed = useMemo(
    () =>
      students.filter((student) => {
        const row = draft[student.student_id];
        if (!row?.status) return false;
        const nextExam = examMode ? row.examTaken : null;
        const savedRow = student.attendance;
        if (!savedRow) return true;
        return savedRow.status !== row.status || (savedRow.exam_taken ?? null) !== nextExam;
      }),
    [students, draft, examMode],
  );

  const save = useApiAction(async (entries: AttendanceEntry[]) => {
    const { data } = await http.put<SessionDetail>(
      `/admin/attendance/sessions/${sessionId}`,
      entries,
    );
    return data;
  });

  const runSave = useCallback(async () => {
    if (changed.length === 0) return;
    const entries: AttendanceEntry[] = changed.map((student) => {
      const row = draft[student.student_id];
      return {
        student_id: student.student_id,
        status: row.status as AttendanceStatus,
        exam_taken: examMode ? row.examTaken : null,
      };
    });
    const data = await save.run(entries);
    if (data) {
      detail.setData(data);
      setSaved(data.triggers ?? null);
      if (canMakeup) void makeups.reload();
    }
    // detail/makeups 는 매 렌더 새 객체라 의존성에서 뺀다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [changed, draft, examMode, canMakeup]);

  // ⌘S · Ctrl+S 로 저장 — 명단을 훑다가 손을 떼지 않고 저장한다.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        void runSave();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [runSave]);

  const fillBlanks = () => {
    const before = draft;
    const blanks = students.filter((s) => !draft[s.student_id]?.status);
    if (blanks.length === 0) return;
    setDraft((prev) => {
      const next = { ...prev };
      for (const student of blanks) {
        next[student.student_id] = { ...next[student.student_id], status: "출석" };
      }
      return next;
    });
    toast.show(`미입력 ${blanks.length}명을 출석으로 표시했습니다. 아직 저장 전입니다.`, {
      action: { label: "되돌리기", onClick: () => setDraft(before) },
    });
  };

  const [approvingId, setApprovingId] = useState<number | null>(null);
  const approve = useApiAction(async (makeupId: number) => {
    await http.post(`/admin/makeup-requests/${makeupId}/approve`);
  });

  const makeupByStudent = useMemo(() => {
    const map = new Map<number, MakeupRow>();
    const date = detail.data?.session.session_date;
    if (!date) return map;
    for (const row of makeups.data ?? []) {
      if (row.session_date !== date) continue;
      map.set(row.student_id, row);
    }
    return map;
  }, [makeups.data, detail.data]);

  if (detail.loading) return <Loading label="명단을 불러오는 중…" />;
  if (detail.error)
    return (
      <>
        <PageHeader title="출결 입력" />
        <ErrorState description={detail.error} onRetry={detail.reload} />
      </>
    );
  if (!detail.data) return null;

  const session = detail.data.session;
  const visible = blankOnly ? students.filter((s) => !draft[s.student_id]?.status) : students;

  const columns: Column<RosterStudent>[] = [
    {
      key: "unique_id",
      header: "원번",
      numeric: true,
      width: "6rem",
      sortValue: (r) => r.unique_id,
      cell: (r) => r.unique_id,
    },
    {
      key: "name",
      header: "이름",
      sortValue: (r) => r.name ?? "",
      cell: (r) => (
        <span className="ops-name">
          {changed.some((c) => c.student_id === r.student_id) && (
            <span className="ops-dot" aria-hidden="true" />
          )}
          <span>{r.name ?? "이름 미등록"}</span>
          {r.enrollment_status !== "등록" && <StatusBadge status={r.enrollment_status} />}
          <span className="sr-only">
            {changed.some((c) => c.student_id === r.student_id) ? "저장 전 변경됨" : ""}
          </span>
        </span>
      ),
    },
    {
      key: "class",
      header: "반",
      width: "6rem",
      cell: (r) => r.current_class ?? <span className="ops-dash">—</span>,
    },
    {
      key: "status",
      header: "출결",
      width: "11.5rem",
      cell: (r) => (
        <StatusPicker
          name={`att-${r.student_id}`}
          label={`${r.name ?? r.unique_id} 출결`}
          value={draft[r.student_id]?.status ?? ""}
          onChange={(status) => setRow(r.student_id, { status })}
        />
      ),
    },
    ...(examMode
      ? [
          {
            key: "exam",
            header: "현장 시험",
            align: "center" as const,
            width: "7rem",
            cell: (r: RosterStudent) => (
              <span className="ops-examcell">
                <Checkbox
                  checked={draft[r.student_id]?.examTaken ?? false}
                  onChange={(event) => setRow(r.student_id, { examTaken: event.target.checked })}
                  label={<span className="sr-only">{r.name ?? r.unique_id} 현장 시험 응시</span>}
                />
              </span>
            ),
          },
        ]
      : []),
    ...(canMakeup
      ? [
          {
            key: "makeup",
            header: "동보(복습영상)",
            width: "11rem",
            cell: (r: RosterStudent) => {
              if (r.attendance?.status !== "결석") return <span className="ops-dash">—</span>;
              const row = makeupByStudent.get(r.student_id);
              if (!row) return <span className="ops-sub">신청 없음</span>;
              if (row.status === "신청")
                return (
                  <Button
                    size="sm"
                    loading={approve.pending && approvingId === row.makeup_id}
                    onClick={async () => {
                      setApprovingId(row.makeup_id);
                      await approve.run(row.makeup_id);
                      setApprovingId(null);
                      void makeups.reload();
                    }}
                  >
                    승인·지급
                  </Button>
                );
              return <StatusBadge status={row.status} />;
            },
          },
        ]
      : []),
    {
      key: "recorded",
      header: "저장된 값",
      width: "10rem",
      cell: (r) =>
        r.attendance ? (
          <span className="ops-name">
            <StatusBadge status={r.attendance.status} />
            {r.attendance.updated_at && <span className="ops-sub">정정 {stamp(r.attendance.updated_at)}</span>}
          </span>
        ) : (
          <span className="ops-sub">아직 없음</span>
        ),
    },
  ];

  return (
    <>
      <PageHeader
        title={`${longDate(session.session_date)} 출결`}
        description={`${sessionLabel(session)} · 명단 ${students.length}명${session.memo ? ` · ${session.memo}` : ""}`}
        actions={
          <Link to="/admin/attendance">
            <Button variant="ghost">회차 목록</Button>
          </Link>
        }
      />

      <div className="ops-bar">
        <div className="ops-figs">
          <Fig tone="present" n={live.출석} label="출석" />
          <Fig tone="late" n={live.지각} label="지각" />
          <Fig tone="absent" n={live.결석} label="결석" />
          <Fig tone="blank" n={live.미입력} label="미입력" />
        </div>

        <div className="ops-bar__actions">
          {changed.length > 0 && (
            <span className="ops-bar__dirty">
              저장 전 변경 <b className="num">{changed.length}</b>명
            </span>
          )}
          <Button size="sm" onClick={fillBlanks} disabled={live.미입력 === 0}>
            {live.미입력 > 0 ? `미입력 ${live.미입력}명 전원 출석` : "미입력 전원 출석"}
          </Button>
          <Button
            size="sm"
            variant="primary"
            loading={save.pending}
            disabled={changed.length === 0}
            onClick={() => void runSave()}
          >
            저장
          </Button>
        </div>
      </div>

      <div className="ui-stack">
        {save.error && <Alert tone="danger">{save.error}</Alert>}
        {approve.error && <Alert tone="danger">{approve.error}</Alert>}
        {saved && <SavedSummary triggers={saved} onClose={() => setSaved(null)} />}

        <Card padding="none">
          <div
            className="ops-toolbar"
            style={{ padding: "var(--space-sm) var(--space-md)", alignItems: "center" }}
          >
            <Checkbox
              checked={examMode}
              onChange={(event) => setExamMode(event.target.checked)}
              label="이 회차에 현장 시험이 있었습니다"
            />
            <Checkbox
              checked={blankOnly}
              onChange={(event) => setBlankOnly(event.target.checked)}
              label={`미입력한 학생만 보기 (${live.미입력}명)`}
            />
            <p className="ops-keys" style={{ marginLeft: "auto" }}>
              <span>
                <kbd>Tab</kbd> 다음 학생
              </span>
              <span>
                <kbd>←</kbd> <kbd>→</kbd> 출석 · 지각 · 결석
              </span>
              <span>
                <kbd>⌘</kbd>+<kbd>S</kbd> 저장
              </span>
            </p>
          </div>

          <Table
            caption={`${session.session_date} 회차 수강생 명단`}
            dense
            columns={columns}
            rows={visible}
            rowKey={(r) => r.student_id}
            empty={
              blankOnly
                ? "미입력한 학생이 없습니다. 전원 출결이 표시돼 있습니다."
                : "이 회차에 배정된 수강생이 없습니다. 커리큘럼 주차와 강좌 수강 등록을 확인하세요."
            }
          />

          <p className="ops-note" style={{ padding: "var(--space-md)" }}>
            <strong>출석</strong>으로 저장하면 그 주차 복습영상 권한이 자동으로 나가고,{" "}
            <strong>결석</strong>으로 저장하면 학부모 통화 카드가 상담 대기열에 쌓입니다.
            {canMakeup && " 결석 학생이 동보를 신청하면 이 표에서 바로 승인할 수 있습니다."}
          </p>
        </Card>
      </div>
    </>
  );
}

function SavedSummary({
  triggers,
  onClose,
}: {
  triggers: AttendanceTriggers;
  onClose: () => void;
}) {
  const parts: string[] = [];
  if (triggers.video_grants_created > 0)
    parts.push(`복습영상 ${triggers.video_grants_created}건 지급`);
  if (triggers.video_grants_reactivated > 0)
    parts.push(`영상 권한 ${triggers.video_grants_reactivated}건 재활성`);
  if (triggers.video_grants_revoked > 0)
    parts.push(`영상 권한 ${triggers.video_grants_revoked}건 회수`);
  if (triggers.counselings_created > 0)
    parts.push(`결석 상담 카드 ${triggers.counselings_created}건 생성`);
  if (triggers.counselings_removed > 0)
    parts.push(`상담 카드 ${triggers.counselings_removed}건 정리`);

  return (
    <Alert tone="success" onClose={onClose}>
      {parts.length > 0
        ? `출결을 저장했습니다 — ${parts.join(" · ")}.`
        : "출결을 저장했습니다. 이번 저장으로 새로 나간 영상 권한이나 상담 카드는 없습니다."}
    </Alert>
  );
}

function StatusPicker({
  name,
  label,
  value,
  onChange,
}: {
  name: string;
  label: string;
  value: AttendanceStatus | "";
  onChange: (status: AttendanceStatus) => void;
}) {
  return (
    <span className="ops-seg" role="radiogroup" aria-label={label}>
      {ATTENDANCE_STATUSES.map((status) => (
        <label key={status} className={`ops-seg__opt ops-seg__opt--${TONE[status]}`}>
          <input
            type="radio"
            name={name}
            value={status}
            checked={value === status}
            onChange={() => onChange(status)}
          />
          <span>{status}</span>
        </label>
      ))}
    </span>
  );
}

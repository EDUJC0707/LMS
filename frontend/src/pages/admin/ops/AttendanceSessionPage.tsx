/**
 * 출결 입력 — 회차 명단(핵심 화면).
 *
 * 호출: GET·PUT /api/admin/attendance/sessions/{id}
 *      · GET  /api/admin/makeup-requests            (동보 지급 여부 확인)
 *      · POST /api/admin/attendance/sessions/{id}/notify  (개별 출결 통지)
 *
 * 설계 요지
 * - 집계 바를 상단에 고정한다. 30명을 훑는 동안에도 "몇 명 남았나"가 늘 보인다.
 * - **버튼은 저장이 아니라 `출결 확정` 이다**(FLOW 3-5·3-11). 출결표는 OMR 이
 *   돌 때마다 스스로 바뀌므로 조교가 저장할 것이 없고, 누르는 뜻은 "이제
 *   내보낸다" 다 — 그래서 **손댄 행이 없어도 눌린다.** 보내는 것은 바꾼 행만
 *   이고(부분 upsert), 서버가 명단 전체에 지급을 돌린다.
 * - 확정 응답의 triggers 를 문장으로 옮긴다 — 이 시스템의 자동화를 사람이
 *   체감하는 유일한 지점이다.
 */
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";

import { http, useApi, useApiAction } from "../../../api";
import { useMe } from "../../../auth";
import { attendanceTone, shortAttendance } from "../../../features/attendance";
import {
  Alert,
  Button,
  Card,
  Checkbox,
  ErrorState,
  Loading,
  StatusBadge,
  Table,
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

type Draft = { status: AttendanceStatus; examTaken: boolean };
type DraftMap = Record<number, Draft>;

function draftFrom(students: RosterStudent[]): DraftMap {
  const next: DraftMap = {};
  for (const student of students) {
    if (student.is_withdrawn) continue;
    next[student.student_id] = {
      status: student.attendance?.status ?? "미입력",
      examTaken: student.attendance?.exam_taken === true,
    };
  }
  return next;
}

export default function AttendanceSessionPage() {
  const { sessionId } = useParams();
  const { hasFeature } = useMe();
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
  const [result, setResult] = useState<AttendanceTriggers | null>(null);
  const [onsiteId, setOnsiteId] = useState("");

  const students = useMemo(() => detail.data?.students ?? [], [detail.data]);

  // 집계 바는 상단바 아래에 한 겹 더 고정된다. 아래 표는 자기 높이를 그만큼
  // 더 줄여야 페이지를 끝까지 내렸을 때 열 이름이 이 바 뒤로 들어가지 않는다
  // (계산은 ops.css `--table-extra-chrome`).
  // 이 바는 flex-wrap 이라 높이가 폭과 내용에 따라 변한다 — 실측 82px(1280↑)
  // ·134px(768~1024)·194px(375~414)·254px(320), 게다가 회차 메모가 길면 넓은
  // 폭에서도 한 줄 더 늘어난다. 상수로 잡을 수 없어 바가 스스로 재서 알린다.
  const barRef = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const node = barRef.current;
    if (!node) return;
    const root = document.documentElement;
    // offsetHeight 는 소수를 버린다(82.4 → 82). 올려 잡아야 모자라지 않는다.
    const write = () =>
      root.style.setProperty(
        "--ops-bar-height",
        `${Math.ceil(node.getBoundingClientRect().height)}px`,
      );
    write();
    const observer = new ResizeObserver(write);
    observer.observe(node);
    return () => {
      observer.disconnect();
      root.style.removeProperty("--ops-bar-height");
    };
  }, [detail.data]);

  useEffect(() => {
    if (!detail.data) return;
    setDraft(draftFrom(detail.data.students));
    // 현장 시험 기록이 하나라도 있으면 시험 열을 켠 채로 연다.
    setExamMode(detail.data.students.some((s) => s.attendance?.exam_taken != null));
  }, [detail.data]);

  const setRow = (studentId: number, patch: Partial<Draft>) =>
    setDraft((prev) => ({
      ...prev,
      [studentId]: {
        ...(prev[studentId] ?? { status: "미입력", examTaken: false }),
        ...patch,
      },
    }));

  // 퇴원 행은 입력 대상이 아니라 집계에도 넣지 않는다 — 넣으면 미입력이
  // 영원히 0 이 되지 않아 "몇 명 남았나"가 거짓말을 한다(서버 summary 와 같은 규칙).
  const entryTargets = useMemo(() => students.filter((s) => !s.is_withdrawn), [students]);

  const live = useMemo(() => {
    const counts = { 미입력: 0, 출석: 0, 결석: 0, "결석(동보)": 0, "결석(현보)": 0 };
    for (const student of entryTargets) {
      counts[draft[student.student_id]?.status ?? "미입력"] += 1;
    }
    return counts;
  }, [entryTargets, draft]);

  const changed = useMemo(
    () =>
      entryTargets.filter((student) => {
        const row = draft[student.student_id];
        if (!row) return false;
        const nextExam = examMode ? row.examTaken : null;
        const stored = student.attendance;
        // 기록이 없는데 미입력이면 보낼 것이 없다 — 둘은 같은 뜻이다(FLOW 3-4)
        if (!stored) return row.status !== "미입력";
        return stored.status !== row.status || (stored.exam_taken ?? null) !== nextExam;
      }),
    [entryTargets, draft, examMode],
  );

  const confirmApi = useApiAction(async (entries: AttendanceEntry[]) => {
    const { data } = await http.put<SessionDetail>(
      `/admin/attendance/sessions/${sessionId}`,
      entries,
    );
    return data;
  });

  const runConfirm = useCallback(async () => {
    const entries: AttendanceEntry[] = changed.map((student) => {
      const row = draft[student.student_id];
      return {
        student_id: student.student_id,
        status: row.status,
        exam_taken: examMode ? row.examTaken : null,
      };
    });
    const data = await confirmApi.run(entries);
    if (data) {
      detail.setData(data);
      setResult(data.triggers ?? null);
      if (canMakeup) void makeups.reload();
    }
    // detail/makeups 는 매 렌더 새 객체라 의존성에서 뺀다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [changed, draft, examMode, canMakeup]);

  // 명단 밖 학생을 이 반 출결표에 올린다(FLOW 3-4) — 원래 반에는 `결석(현보)` 가
  // 같이 찍힌다. 조교가 지면을 보고 "다른 반 학생"이라고 판단한 뒤 누르는 자리다.
  const onsite = useApiAction(async (loginId: string) => {
    const { data } = await http.post<SessionDetail>(
      `/admin/attendance/sessions/${sessionId}/onsite`,
      { login_id: loginId },
    );
    return data;
  });

  // 퇴원·퇴원 취소 — 여기가 유일한 입구다(FLOW 3-4). 저장하는 그 순간 로그인이
  // 막히고, 자녀가 이 학생뿐인 학부모도 같이 막힌다. 되돌리는 것도 같은 버튼이다.
  const withdrawal = useApiAction(async (student: RosterStudent) => {
    const body = { student_id: student.student_id };
    if (student.is_withdrawn) await http.delete("/admin/attendance/withdraw", { data: body });
    else await http.post("/admin/attendance/withdraw", body);
  });

  const runWithdrawal = async (student: RosterStudent) => {
    await withdrawal.run(student);
    void detail.reload();
  };

  // 첫 확정에만 문자가 자동으로 나간다(FLOW 3-11) — 그 뒤에 정정된 학생은
  // 조교가 이 버튼으로 보낸다. 결석에는 버튼 자체가 없다(아래 열).
  const notify = useApiAction(async (studentId: number) => {
    const { data } = await http.post<SessionDetail>(
      `/admin/attendance/sessions/${sessionId}/notify`,
      { student_id: studentId },
    );
    return data;
  });

  const runNotify = async (studentId: number) => {
    const data = await notify.run(studentId);
    if (!data) return;
    detail.setData(data);
    setResult(data.triggers ?? null);
  };

  const runOnsite = async () => {
    const data = await onsite.run(onsiteId.trim());
    if (!data) return;
    detail.setData(data);
    setResult(data.triggers ?? null);
    setOnsiteId("");
  };

  // ⌘S · Ctrl+S 로 확정 — 명단을 훑다가 손을 떼지 않고 내보낸다.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        void runConfirm();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [runConfirm]);

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
  if (detail.error) return <ErrorState description={detail.error} onRetry={detail.reload} />;
  if (!detail.data) return null;

  const session = detail.data.session;
  const summary = detail.data.summary;
  const visible = blankOnly
    ? entryTargets.filter((s) => (draft[s.student_id]?.status ?? "미입력") === "미입력")
    : students;

  const columns: Column<RosterStudent>[] = [
    {
      // 원번은 2026-07-29 개정으로 이름이 섞인 값이 됐다(`김하늘0001`) — 숫자 열이
      // 아니므로 numeric(모노·우측정렬)을 걸지 않고, 6rem 고정폭도 뗐다(줄바꿈됐다).
      key: "login_id",
      header: "원번",
      sortValue: (r) => r.login_id ?? "",
      cell: (r) => r.login_id ?? "—",
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
            {changed.some((c) => c.student_id === r.student_id) ? "확정 전 변경됨" : ""}
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
      width: "15rem",
      cell: (r) =>
        r.is_withdrawn ? (
          <span className="ops-withdrawn">퇴원</span>
        ) : (
          <StatusPicker
            name={`att-${r.student_id}`}
            label={`${r.name ?? r.login_id} 출결`}
            value={draft[r.student_id]?.status ?? "미입력"}
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
            cell: (r: RosterStudent) =>
              r.is_withdrawn ? (
                <span className="ops-dash">—</span>
              ) : (
                <span className="ops-examcell">
                  <Checkbox
                    checked={draft[r.student_id]?.examTaken ?? false}
                    onChange={(event) =>
                      setRow(r.student_id, { examTaken: event.target.checked })
                    }
                    label={
                      <span className="sr-only">{r.name ?? r.login_id} 현장 시험 제출</span>
                    }
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
            // 승인이 없다(FLOW 3-4) — 신청 + 결석 확인이 차면 저장이 곧 지급이다.
            // 담임이 `결석(동보)` 를 찍든 학생이 신청하든 이 열에는 결과만 뜬다.
            cell: (r: RosterStudent) => {
              const status = r.attendance?.status;
              if (status !== "결석" && status !== "결석(동보)")
                return <span className="ops-dash">—</span>;
              const row = makeupByStudent.get(r.student_id);
              if (!row) return <span className="ops-sub">신청 없음</span>;
              return <StatusBadge status={row.status} />;
            },
          },
        ]
      : []),
    {
      key: "withdrawal",
      header: "퇴원",
      align: "right" as const,
      width: "7rem",
      cell: (r: RosterStudent) => (
        <Button
          size="sm"
          variant="ghost"
          disabled={withdrawal.pending}
          onClick={() => void runWithdrawal(r)}
        >
          {r.is_withdrawn ? "퇴원 취소" : "퇴원"}
        </Button>
      ),
    },
    ...(session.confirmed_at
      ? [
          {
            key: "notice",
            header: "출결 통지",
            width: "11rem",
            cell: (r: RosterStudent) =>
              r.notice === "해당 없음" ? (
                <span className="ops-dash">— 해당 없음</span>
              ) : r.notice === "발송" ? (
                <span className="ops-sub">✓ 발송</span>
              ) : (
                <span className="ops-name">
                  <span className="ops-sub">⚠ {r.notice}</span>
                  <Button
                    size="sm"
                    variant="ghost"
                    loading={notify.pending}
                    onClick={() => void runNotify(r.student_id)}
                  >
                    보내기
                  </Button>
                </span>
              ),
          },
        ]
      : []),
    {
      key: "recorded",
      // "저장된 값" 이 아니다 — OMR 도 여기에 쓰므로(FLOW 3-2) 저장이라는 말이
      // 주체를 사람으로 오해하게 만든다. 이 열은 **서버에 있는 지금 값**이다.
      header: "현재 값",
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

  // 상단바는 "출결 입력"까지만 말한다 — 어느 회차인지는 본문이 들어야 한다.
  // 카드 머리가 아니라 고정 바에 둔 이유: 30명을 훑는 내내 "몇 명 남았나"와
  // "어느 회차인가"가 같이 붙어 있어야 다른 회차에 잘못 입력하지 않는다.
  // "회차 목록" 링크는 뺐다 — 좌측 레일의 활성 항목이 바로 그 경로다.
  return (
    <>
      <div className="ops-bar" ref={barRef}>
        <div className="ops-id">
          <span className="ops-id__title">{longDate(session.session_date)}</span>
          <span className="ops-id__meta">
            {sessionLabel(session)} · 명단 {summary.total}명
            {summary.퇴원 > 0 ? ` · 퇴원 ${summary.퇴원}명` : ""}
            {session.memo ? ` · ${session.memo}` : ""}
          </span>
        </div>

        <div className="ops-figs">
          <Fig tone="present" n={live.출석} label="출석" />
          <Fig tone="absent" n={live.결석} label="결석" />
          <Fig tone="makeup" n={live["결석(동보)"]} label="동보" />
          <Fig tone="onsite" n={live["결석(현보)"]} label="현보" />
          <Fig tone="blank" n={live.미입력} label="미입력" />
        </div>

        <div className="ops-bar__actions">
          {session.confirmed_at && (
            <span className="ops-bar__stamp">확정 {stamp(session.confirmed_at)}</span>
          )}
          {changed.length > 0 && (
            <span className="ops-bar__dirty">
              확정 전 변경 <b className="num">{changed.length}</b>명
            </span>
          )}
          <Button
            size="sm"
            variant="primary"
            loading={confirmApi.pending}
            onClick={() => void runConfirm()}
          >
            출결 확정
          </Button>
        </div>
      </div>

      <div className="ui-stack">
        {confirmApi.error && <Alert tone="danger">{confirmApi.error}</Alert>}
        {onsite.error && <Alert tone="danger">{onsite.error}</Alert>}
        {notify.error && <Alert tone="danger">{notify.error}</Alert>}
        {withdrawal.error && <Alert tone="danger">{withdrawal.error}</Alert>}
        {result && <ConfirmSummary triggers={result} onClose={() => setResult(null)} />}

        <Card padding="none" className="ops-tablecard">
          <div className="ops-toolbar ops-toolbar--center ops-cardbar">
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
            <form
              className="ui-row"
              onSubmit={(event) => {
                event.preventDefault();
                void runOnsite();
              }}
            >
              <label className="ops-toolbar__field">
                <span className="ops-toolbar__label">원번</span>
                <input
                  className="ui-input"
                  value={onsiteId}
                  onChange={(event) => setOnsiteId(event.target.value)}
                />
              </label>
              <Button
                size="sm"
                type="submit"
                loading={onsite.pending}
                disabled={onsiteId.trim() === ""}
              >
                현보 추가
              </Button>
            </form>
            <p className="ops-keys">
              <span>
                <kbd>Tab</kbd> 다음 학생
              </span>
              <span>
                <kbd>←</kbd> <kbd>→</kbd> 미입력 · 출석 · 결석 · 동보 · 현보
              </span>
              <span>
                <kbd>⌘</kbd>+<kbd>S</kbd> 출결 확정
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
              blankOnly ? "미입력한 학생이 없습니다" : "이 회차에 배정된 수강생이 없습니다"
            }
          />
        </Card>
      </div>
    </>
  );
}

function ConfirmSummary({
  triggers,
  onClose,
}: {
  triggers: AttendanceTriggers;
  onClose: () => void;
}) {
  const parts: string[] = [];
  if (triggers.makeups_granted > 0) parts.push(`동보 ${triggers.makeups_granted}건 지급`);
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
  if (triggers.notifications_queued > 0)
    parts.push(`출결 통지 ${triggers.notifications_queued}건`);

  return (
    <Alert tone="success" onClose={onClose}>
      {parts.length > 0
        ? `출결을 확정했습니다 — ${parts.join(" · ")}`
        : "출결을 확정했습니다"}
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
  value: AttendanceStatus;
  onChange: (status: AttendanceStatus) => void;
}) {
  return (
    <span className="ops-seg" role="radiogroup" aria-label={label}>
      {ATTENDANCE_STATUSES.map((status) => (
        <label
          key={status}
          className={`ops-seg__opt ops-seg__opt--${attendanceTone(status)}`}
        >
          <input
            type="radio"
            name={name}
            value={status}
            checked={value === status}
            onChange={() => onChange(status)}
            // 찍은 것을 다시 누르면 해제 — 라디오는 스스로 못 푼다
            onClick={() => value === status && onChange("미입력")}
            aria-label={status}
          />
          <span aria-hidden="true">{shortAttendance(status)}</span>
        </label>
      ))}
    </span>
  );
}

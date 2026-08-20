/**
 * 반별 관리 — 격자 (FLOW 3-1).
 * 호출: GET /api/admin/attendance/classes/{class_id}
 *      · GET /api/admin/attendance/sessions   (반 고르기 — 목록 API 를 따로 두지 않는다)
 *
 * 가로가 주차, 세로가 학생이다. 조교가 수업 끝나고 하는 일은 세로(그 주 전원 —
 * 주차 이름을 누르면 그 회차 출결표로 간다)고, 학부모 전화가 오면 보는 것은
 * 가로(그 학생이 이 반에서 어땠는가)다.
 *
 * **읽기만 한다.** 출결을 고치는 문은 주차(3-2)뿐이다 — 여기서 칸을 바로 고치면
 * 그 쓰기가 `출결 확정`(3-5)을 지나쳐 영상과 통지가 출결과 갈린다.
 */
import { useMemo } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { http, useApi } from "../../../api";
import { Card, ErrorState, Loading, Select, StatusBadge, Table } from "../../../components";
import type { Column } from "../../../components";
import { attendanceTone, shortAttendance } from "../../../features/attendance";
import { shortDate } from "./format";
import { cellFor, enteredWeeks } from "./grid";
import "./ops.css";
import type { ClassGrid, GridStudent, SessionBlock } from "./types";

export default function ClassGridPage() {
  const { classId } = useParams();
  const navigate = useNavigate();

  // 반 목록은 회차 목록에서 뽑는다(AttendancePage 와 같은 방식) — 같은 질문에
  // 답하는 API 를 두 개 두지 않는다.
  const sessions = useApi(
    async () =>
      (await http.get<{ sessions: SessionBlock[] }>("/admin/attendance/sessions")).data.sessions,
    [],
  );

  const classes = useMemo(() => {
    const seen = new Map<number, string>();
    for (const s of sessions.data ?? []) if (s.klass) seen.set(s.klass.class_id, s.klass.name);
    return [...seen].map(([id, name]) => ({ id, name }));
  }, [sessions.data]);

  const grid = useApi<ClassGrid | null>(
    async () =>
      classId
        ? (await http.get<ClassGrid>(`/admin/attendance/classes/${classId}`)).data
        : null,
    [classId],
  );

  const weeks = grid.data?.weeks ?? [];
  const students = grid.data?.students ?? [];
  // 아직 아무도 안 찍은 주차는 반 전체가 미입력이다 — 학생 하나만 보면 x 로 보인다.
  const entered = enteredWeeks(students, weeks.length);
  const columns: Column<GridStudent>[] = [
    {
      key: "name",
      header: "이름",
      width: "12rem",
      sortValue: (r) => r.name ?? "",
      cell: (r) => (
        <span className="ops-name">
          <span>{r.name ?? "이름 미등록"}</span>
          {r.enrollment_status !== "등록" && <StatusBadge status={r.enrollment_status} />}
        </span>
      ),
    },
    ...weeks.map((week, index) => ({
      key: `w${week.session_id}`,
      align: "center" as const,
      width: "5rem",
      header: (
        <Link to={`/admin/attendance/${week.session_id}`}>
          {week.week_no === null ? shortDate(week.session_date) : `${week.week_no}주차`}
        </Link>
      ),
      cell: (r: GridStudent) => {
        const value = cellFor(r.cells, index, entered[index]);
        if (value === "미입력") return null;
        if (value === "x") return <span className="ops-grid__none">x</span>;
        return (
          <span className={`ops-grid__mark ops-grid__mark--${attendanceTone(value)}`}>
            {shortAttendance(value)}
          </span>
        );
      },
    })),
  ];

  return (
    <div className="ui-stack">
      <Card padding="none" className="ops-tablecard">
        <div className="ops-toolbar ops-cardbar">
          <label className="ops-toolbar__field">
            <span className="ops-toolbar__label">반</span>
            <Select
              value={classId ?? ""}
              onChange={(event) =>
                navigate(event.target.value ? `/admin/class/${event.target.value}` : "/admin/class")
              }
            >
              <option value="">반 고르기</option>
              {classes.map((klass) => (
                <option key={klass.id} value={String(klass.id)}>
                  {klass.name}
                </option>
              ))}
            </Select>
          </label>
        </div>

        {sessions.loading || grid.loading ? (
          <div className="ops-cardstate">
            <Loading label="반을 불러오는 중…" />
          </div>
        ) : grid.error ? (
          <ErrorState description={grid.error} onRetry={grid.reload} />
        ) : sessions.error ? (
          <ErrorState description={sessions.error} onRetry={sessions.reload} />
        ) : (
          <div className="ops-grid">
            <Table
              caption={grid.data ? `${grid.data.klass.name} 출결` : "반별 출결"}
              dense
              columns={columns}
              rows={students}
              rowKey={(r) => r.student_id}
              empty={classId ? "이 반에는 학생이 없습니다" : "반을 고르세요"}
            />
          </div>
        )}
      </Card>
    </div>
  );
}

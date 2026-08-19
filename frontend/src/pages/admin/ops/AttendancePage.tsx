/**
 * 출결 입력 — 회차 고르기.
 * 호출: GET /api/admin/attendance/sessions?date=YYYY-MM-DD
 *
 * 수업 당일 쓰는 화면이라 기본 탭은 "오늘 이후" — 오늘 회차가 맨 위에 온다.
 * 지난 회차는 최근 것부터 본다(정정하러 들어오는 동선).
 */
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { http, useApi } from "../../../api";
import { Button, Card, ErrorState, Loading, Select, Table, Tabs } from "../../../components";
import type { Column } from "../../../components";
import { relativeDay, sessionLabel, shortDate, todayISO } from "./format";
import "./ops.css";
import type { SessionBlock } from "./types";

type Range = "예정" | "지난" | "전체";

export default function AttendancePage() {
  const navigate = useNavigate();
  const today = todayISO();
  const [date, setDate] = useState("");
  const [courseId, setCourseId] = useState("");
  const [classId, setClassId] = useState("");
  const [range, setRange] = useState<Range>("예정");

  const sessions = useApi(
    async () =>
      (
        await http.get<{ sessions: SessionBlock[] }>("/admin/attendance/sessions", {
          params: date ? { date } : {},
        })
      ).data.sessions,
    [date],
  );

  const all = useMemo(() => sessions.data ?? [], [sessions.data]);

  const courses = useMemo(() => {
    const seen = new Map<number, string>();
    for (const s of all) if (s.course) seen.set(s.course.course_id, s.course.name);
    return [...seen].map(([id, name]) => ({ id, name }));
  }, [all]);

  // 반은 고른 강좌 안에서만 보여 준다 — 반 이름은 커리를 안 담으므로
  // 전체 강좌의 반을 한 줄에 늘어놓으면 어느 커리의 반인지 알 수 없다.
  const classes = useMemo(() => {
    const seen = new Map<number, string>();
    for (const s of all) {
      if (courseId && String(s.course?.course_id ?? "") !== courseId) continue;
      if (s.klass) seen.set(s.klass.class_id, s.klass.name);
    }
    return [...seen].map(([id, name]) => ({ id, name }));
  }, [all, courseId]);

  const byCourse = useMemo(() => {
    const rows = courseId
      ? all.filter((s) => String(s.course?.course_id ?? "") === courseId)
      : all;
    return classId ? rows.filter((s) => String(s.klass?.class_id ?? "") === classId) : rows;
  }, [all, courseId, classId]);

  const ahead = useMemo(() => byCourse.filter((s) => s.session_date >= today), [byCourse, today]);
  const past = useMemo(
    () => byCourse.filter((s) => s.session_date < today).reverse(),
    [byCourse, today],
  );

  const rows = date ? byCourse : range === "예정" ? ahead : range === "지난" ? past : byCourse;

  const columns: Column<SessionBlock>[] = [
    {
      key: "date",
      header: "수업일",
      width: "14rem",
      sortValue: (r) => r.session_date,
      cell: (r) => (
        <span className="ops-name">
          <span>{shortDate(r.session_date)}</span>
          <span className="ops-sub">{relativeDay(r.session_date, today)}</span>
        </span>
      ),
    },
    {
      key: "no",
      header: "차시",
      numeric: true,
      width: "5rem",
      sortValue: (r) => r.session_no ?? 0,
      cell: (r) => (r.session_no === null ? <span className="ops-dash">—</span> : r.session_no),
    },
    {
      key: "course",
      header: "반 · 강좌 · 주차",
      cell: (r) => sessionLabel({ ...r, session_no: null }),
    },
    {
      key: "grade",
      header: "대상",
      width: "7rem",
      cell: (r) =>
        r.target_grade === null ? (
          <span className="ops-dash">전 학년</span>
        ) : (
          <span className="num">고{r.target_grade}</span>
        ),
    },
    {
      key: "memo",
      header: "메모",
      cell: (r) => r.memo ?? <span className="ops-dash">—</span>,
    },
    {
      key: "go",
      header: "출결",
      align: "right",
      width: "9rem",
      cell: (r) => (
        <Link to={`/admin/attendance/${r.session_id}`} onClick={(e) => e.stopPropagation()}>
          명단 열기
        </Link>
      ),
    },
  ];

  // 필터·탭·표를 카드 하나에 넣는다. 전에는 필터가 따로 뜬 카드(flat)였고
  // 불러오는 동안 표 카드가 통째로 사라져 로딩 문구가 종이 위에 홀로 떴다.
  // 지금은 조건 줄이 제자리에 남고 그 아래에서만 내용이 바뀐다.
  return (
    <div className="ui-stack">
      <Card padding="none" className="ops-tablecard">
        <div className="ops-toolbar ops-cardbar">
          <label className="ops-toolbar__field">
            <span className="ops-toolbar__label">수업일</span>
            <input
              className="ui-input"
              type="date"
              value={date}
              onChange={(event) => setDate(event.target.value)}
            />
          </label>

          {courses.length > 1 && (
            <label className="ops-toolbar__field">
              <span className="ops-toolbar__label">강좌</span>
              <Select
                value={courseId}
                onChange={(event) => {
                  setCourseId(event.target.value);
                  setClassId("");
                }}
              >
                <option value="">전체 강좌</option>
                {courses.map((course) => (
                  <option key={course.id} value={String(course.id)}>
                    {course.name}
                  </option>
                ))}
              </Select>
            </label>
          )}

          {classes.length > 1 && (
            <label className="ops-toolbar__field">
              <span className="ops-toolbar__label">반</span>
              <Select value={classId} onChange={(event) => setClassId(event.target.value)}>
                <option value="">전체 반</option>
                {classes.map((klass) => (
                  <option key={klass.id} value={String(klass.id)}>
                    {klass.name}
                  </option>
                ))}
              </Select>
            </label>
          )}

          <div className="ui-row">
            <Button size="sm" onClick={() => setDate(today)}>
              오늘
            </Button>
            {(date || courseId || classId) && (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  setDate("");
                  setCourseId("");
                  setClassId("");
                }}
              >
                조건 지우기
              </Button>
            )}
          </div>
        </div>

        {sessions.loading ? (
          <Loading label="회차를 불러오는 중…" />
        ) : sessions.error ? (
          <ErrorState description={sessions.error} onRetry={sessions.reload} />
        ) : (
          <>
            {!date && (
              <div className="ops-cardbar ops-cardbar--tabs">
                <Tabs
                  label="회차 범위"
                  value={range}
                  onChange={setRange}
                  items={[
                    { key: "예정", label: "오늘 이후", count: ahead.length },
                    { key: "지난", label: "지난 회차", count: past.length },
                    { key: "전체", label: "전체", count: byCourse.length },
                  ]}
                />
              </div>
            )}
            <Table
              caption="수업 회차 목록"
              dense
              columns={columns}
              rows={rows}
              rowKey={(r) => r.session_id}
              isSelected={(r) => r.session_date === today}
              onRowClick={(r) => navigate(`/admin/attendance/${r.session_id}`)}
              empty={
                date
                  ? `${shortDate(date)}에는 수업 회차가 없습니다`
                  : range === "예정"
                    ? "예정된 회차가 없습니다"
                    : "표시할 회차가 없습니다"
              }
            />
          </>
        )}
      </Card>
    </div>
  );
}

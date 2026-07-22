/**
 * 관리자 출결 입력 — 회차 목록 + 명단 테이블(라디오/응시 선택) + 저장.
 * 저장 응답의 triggers 로 "영상 지급 N건·상담 대기열 N건" 파생 결과를 그대로 보여준다
 * (출결 SSOT 트리거 시연 — PRD 3.1.6).
 */
/* eslint-disable @typescript-eslint/no-explicit-any */
import { FormEvent, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api, errMsg } from "../../api";
import { Msg, useLoad } from "../../ui";

export function AttendanceListPage() {
  const [date, setDate] = useState("");
  const { data, error, loading } = useLoad<any>(
    async () =>
      (await api.get("/admin/attendance/sessions", { params: date ? { date } : {} })).data,
    [date],
  );
  return (
    <section>
      <h2>출결 입력 — 회차 목록</h2>
      <p className="inline">
        날짜 필터: <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
        <button onClick={() => setDate("")}>전체</button>
      </p>
      <Msg error={error} />
      {loading && <p>불러오는 중…</p>}
      {data && (
        <table>
          <thead>
            <tr>
              <th>수업일</th>
              <th>차시</th>
              <th>강좌/주차</th>
              <th>메모</th>
              <th>출결</th>
            </tr>
          </thead>
          <tbody>
            {data.sessions.map((session: any) => (
              <tr key={session.session_id}>
                <td>{session.session_date}</td>
                <td>{session.session_no ?? "-"}</td>
                <td>
                  {session.course ? `${session.course.name} ${session.week_no}주차` : "미매핑"}
                </td>
                <td>{session.memo ?? "-"}</td>
                <td>
                  <Link to={`/bare/admin/attendance/${session.session_id}`}>입력/조회</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

type RowState = { status: string; examTaken: "" | "true" | "false" };

export function AttendanceSessionPage() {
  const { sessionId } = useParams();
  const [rows, setRows] = useState<Record<number, RowState>>({});
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);

  const detail = useLoad<any>(
    async () => (await api.get(`/admin/attendance/sessions/${sessionId}`)).data,
    [sessionId],
  );

  useEffect(() => {
    if (!detail.data) return;
    const next: Record<number, RowState> = {};
    for (const student of detail.data.students) {
      next[student.student_id] = {
        status: student.attendance?.status ?? "",
        examTaken:
          student.attendance?.exam_taken === true
            ? "true"
            : student.attendance?.exam_taken === false
              ? "false"
              : "",
      };
    }
    setRows(next);
  }, [detail.data]);

  const save = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setFeedback(null);
    const entries = Object.entries(rows)
      .filter(([, row]) => row.status !== "")
      .map(([studentId, row]) => ({
        student_id: Number(studentId),
        status: row.status,
        exam_taken: row.examTaken === "" ? null : row.examTaken === "true",
      }));
    if (entries.length === 0) {
      setError("저장할 출결이 없습니다 — 상태를 먼저 선택하세요.");
      return;
    }
    try {
      const { data } = await api.put(`/admin/attendance/sessions/${sessionId}`, entries);
      detail.setData(data);
      const t = data.triggers;
      setFeedback(
        `저장 완료 — 복습영상 지급 ${t.video_grants_created}건 · 재활성 ${t.video_grants_reactivated}건 · 회수 ${t.video_grants_revoked}건 / 상담 대기열 생성 ${t.counselings_created}건 · 정리 ${t.counselings_removed}건`,
      );
    } catch (e) {
      setError(errMsg(e));
    }
  };

  const data = detail.data;
  const setRow = (studentId: number, patch: Partial<RowState>) =>
    setRows((prev) => ({ ...prev, [studentId]: { ...prev[studentId], ...patch } }));

  return (
    <section>
      <h2>
        출결 입력 <Link to="/bare/admin/attendance">(회차 목록으로)</Link>
      </h2>
      <Msg error={detail.error ?? error} ok={feedback} />
      {detail.loading && <p>불러오는 중…</p>}
      {data && (
        <>
          <p>
            <strong>
              {data.session.session_date} {data.session.session_no ?? "-"}차시
            </strong>
            {data.session.course &&
              ` — ${data.session.course.name} ${data.session.week_no}주차`}
          </p>
          <p>
            집계: 출석 {data.summary["출석"]} · 결석 {data.summary["결석"]} · 지각{" "}
            {data.summary["지각"]} · 미입력 {data.summary["미입력"]} / 총 {data.summary.total}명
          </p>
          <form onSubmit={save}>
            <table>
              <thead>
                <tr>
                  <th>학생</th>
                  <th>원번</th>
                  <th>반</th>
                  <th>등록 상태</th>
                  <th>출결(출석 저장 시 영상 자동지급 · 결석 저장 시 상담 대기열)</th>
                  <th>현장 시험 응시</th>
                  <th>기존 입력</th>
                </tr>
              </thead>
              <tbody>
                {data.students.map((student: any) => {
                  const row = rows[student.student_id] ?? { status: "", examTaken: "" };
                  return (
                    <tr key={student.student_id}>
                      <td>
                        {student.name} (#{student.student_id})
                      </td>
                      <td>{student.unique_id}</td>
                      <td>{student.current_class ?? "-"}</td>
                      <td>{student.enrollment_status}</td>
                      <td>
                        {["출석", "결석", "지각"].map((status) => (
                          <label key={status} style={{ marginRight: 8 }}>
                            <input
                              type="radio"
                              name={`att-${student.student_id}`}
                              checked={row.status === status}
                              onChange={() => setRow(student.student_id, { status })}
                            />
                            {status}
                          </label>
                        ))}
                      </td>
                      <td>
                        <select
                          value={row.examTaken}
                          onChange={(e) =>
                            setRow(student.student_id, {
                              examTaken: e.target.value as RowState["examTaken"],
                            })
                          }
                        >
                          <option value="">기록 없음</option>
                          <option value="true">응시</option>
                          <option value="false">미응시</option>
                        </select>
                      </td>
                      <td className="muted">
                        {student.attendance
                          ? `${student.attendance.status}${
                              student.attendance.updated_at ? " (정정됨)" : ""
                            }`
                          : "미입력"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <button type="submit">전체 저장 (upsert + 파생 트리거)</button>
          </form>

          <h3>동보 지급 — 관리자 체크(1차 경로, PRD 3.2.3)</h3>
          <MakeupCheckForm />
        </>
      )}
    </section>
  );
}

function MakeupCheckForm() {
  const [studentId, setStudentId] = useState("");
  const [attendanceId, setAttendanceId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setOk(null);
    try {
      const { data } = await api.post("/admin/attendance/makeup", {
        student_id: Number(studentId),
        attendance_id: Number(attendanceId),
      });
      setOk(
        `동보 지급 완료 — makeup #${data.makeup.makeup_id} (${data.makeup.status}) / 영상권한 #${data.video_grant.grant_id} 주차 ${data.video_grant.course_week_id} · ${data.video_grant.expires_at} 만료`,
      );
    } catch (e) {
      setError(errMsg(e));
    }
  };

  return (
    <>
      <p className="muted">
        결석 출결에만 지급된다(출석·지각이면 400). attendance_id 는 API 응답에 없으므로 동보
        관리 목록·DB에서 확인해 입력한다.
      </p>
      <form onSubmit={submit} className="inline">
        <input
          type="number"
          placeholder="student_id"
          value={studentId}
          onChange={(e) => setStudentId(e.target.value)}
        />
        <input
          type="number"
          placeholder="attendance_id"
          value={attendanceId}
          onChange={(e) => setAttendanceId(e.target.value)}
        />
        <button type="submit">동보 체크(즉시 지급)</button>
      </form>
      <Msg error={error} ok={ok} />
    </>
  );
}

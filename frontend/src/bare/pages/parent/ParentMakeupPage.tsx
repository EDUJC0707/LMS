/** 학부모 동보 신청 — 자녀 결석 목록 + POST /api/parent/makeup-request. */
/* eslint-disable @typescript-eslint/no-explicit-any */
import { FormEvent, useState } from "react";

import { api, errMsg } from "../../api";
import { Msg, useLoad } from "../../ui";
import { currentMonth } from "../student/common";
import { useChild } from "./common";

export default function ParentMakeupPage() {
  const { studentId, picker } = useChild();
  const [attendanceId, setAttendanceId] = useState("");
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  const home = useLoad<any>(
    async () =>
      (
        await api.get("/parent/home", {
          params: {
            month: currentMonth(),
            ...(studentId !== null ? { student_id: studentId } : {}),
          },
        })
      ).data,
    [studentId],
  );

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setResult(null);
    try {
      const { data } = await api.post("/parent/makeup-request", {
        attendance_id: Number(attendanceId),
      });
      setResult(data.makeup);
    } catch (e) {
      setError(errMsg(e));
    }
  };

  const absences: any[] = home.data?.absences ?? [];
  return (
    <section>
      <h2>동보 신청 (학부모)</h2>
      {picker}
      <h3>이달 자녀 결석</h3>
      <table>
        <thead>
          <tr>
            <th>결석일</th>
            <th>동보 상태</th>
          </tr>
        </thead>
        <tbody>
          {absences.length === 0 && (
            <tr>
              <td colSpan={2} className="muted">
                이달 결석 없음
              </td>
            </tr>
          )}
          {absences.map((absence, index) => (
            <tr key={index}>
              <td>{absence.date}</td>
              <td>{absence.makeup_status ?? "미신청"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="muted">
        소비자 API 는 attendance_id 를 내려주지 않는다(현재 백엔드 계약) — 관리자 화면에서
        확인한 id 를 입력. 타인 자녀의 id 를 넣으면 404(존재 비노출)가 떨어진다.
      </p>
      <form onSubmit={submit} className="inline">
        <input
          type="number"
          placeholder="attendance_id"
          value={attendanceId}
          onChange={(e) => setAttendanceId(e.target.value)}
        />
        <button type="submit">동보 신청</button>
      </form>
      <Msg error={error ?? home.error} />
      {result && (
        <p className="ok">
          신청 완료 — 번호 {result.makeup_id} · {result.session_date} ({result.course_name}{" "}
          {result.week_no}주차) · 상태 {result.status}
        </p>
      )}
    </section>
  );
}

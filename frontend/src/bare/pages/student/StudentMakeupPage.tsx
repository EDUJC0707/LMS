/** 동보(결석 보강) 신청 — 예비 경로(PRD 3.2.3). 결석 출결에만 성립. */
/* eslint-disable @typescript-eslint/no-explicit-any */
import { FormEvent, useState } from "react";

import { api, errMsg } from "../../api";
import { Msg, useLoad } from "../../ui";
import { currentMonth } from "./common";

export default function StudentMakeupPage() {
  const [attendanceId, setAttendanceId] = useState("");
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  const home = useLoad<any>(
    async () => (await api.get("/student/home", { params: { month: currentMonth() } })).data,
    [],
  );
  const absentDays: string[] = (home.data?.calendar?.days ?? [])
    .filter((day: any) => day.attendance === "결석")
    .map((day: any) => day.date);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setResult(null);
    try {
      const { data } = await api.post("/student/makeup-request", {
        attendance_id: Number(attendanceId),
      });
      setResult(data.makeup);
    } catch (e) {
      setError(errMsg(e));
    }
  };

  return (
    <section>
      <h2>동보 신청 (학생 예비 경로)</h2>
      <p>
        이달 내 결석일:{" "}
        {absentDays.length > 0 ? absentDays.join(", ") : "없음(다른 달은 홈에서 이동해 확인)"}
      </p>
      <p className="muted">
        소비자 API 는 결석의 attendance_id 를 내려주지 않는다(현재 백엔드 계약) — 관리자
        화면(동보 관리 목록)이나 DB 에서 id 를 확인해 입력한다. 결석이 아닌 출결 id 를 넣으면
        400 사유를 그대로 보여준다.
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
      <Msg error={error} />
      {result && (
        <p className="ok">
          신청 완료 — 번호 {result.makeup_id} · {result.session_date} ({result.course_name}{" "}
          {result.week_no}주차) · 상태 {result.status}. 관리자 승인 시 그 주 복습영상 권한이
          지급됩니다.
        </p>
      )}
    </section>
  );
}

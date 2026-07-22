/** 학부모 캘린더 홈 — GET /api/parent/home (자녀 선택 + 결제·결석 블록). */
import { useState } from "react";

import { api } from "../../api";
import { Msg, useLoad } from "../../ui";
import CalendarView from "../../views/CalendarView";
import { currentMonth } from "../student/common";
import { useChild } from "./common";

export default function ParentHomePage() {
  const { studentId, picker } = useChild();
  const [month, setMonth] = useState(currentMonth());
  const { data, error, loading } = useLoad(
    async () =>
      (
        await api.get("/parent/home", {
          params: { month, ...(studentId !== null ? { student_id: studentId } : {}) },
        })
      ).data,
    [month, studentId],
  );
  return (
    <section>
      <h2>자녀 홈(캘린더)</h2>
      {picker}
      <Msg error={error} />
      {loading && <p>불러오는 중…</p>}
      {data && (
        <CalendarView
          data={data}
          month={month}
          onMonth={setMonth}
          makeupPath={`/bare/parent/makeup${studentId !== null ? `?student_id=${studentId}` : ""}`}
        />
      )}
    </section>
  );
}

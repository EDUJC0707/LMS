/** 학생 캘린더 홈 — GET /api/student/home?month= */
import { useState } from "react";

import { api } from "../../api";
import { DebugNote, currentMonth } from "./common";
import CalendarView from "../../views/CalendarView";
import { Msg, useLoad } from "../../ui";

export default function StudentHomePage() {
  const [month, setMonth] = useState(currentMonth());
  const { data, error, loading } = useLoad(
    async () => (await api.get("/student/home", { params: { month } })).data,
    [month],
  );
  return (
    <section>
      <h2>학생 홈(캘린더)</h2>
      <Msg error={error} />
      {loading && <p>불러오는 중…</p>}
      {data && <CalendarView data={data} month={month} onMonth={setMonth} />}
      <DebugNote />
    </section>
  );
}

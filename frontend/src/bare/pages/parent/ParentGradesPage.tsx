/** 자녀 성적 목록 — GET /api/parent/grades?student_id= (읽기 전용). */
import { api } from "../../api";
import { Msg, useLoad } from "../../ui";
import GradesView from "../../views/GradesView";
import { useChild } from "./common";

export default function ParentGradesPage() {
  const { studentId, picker } = useChild();
  const { data, error, loading } = useLoad(
    async () =>
      (
        await api.get("/parent/grades", {
          params: studentId !== null ? { student_id: studentId } : {},
        })
      ).data,
    [studentId],
  );
  return (
    <section>
      <h2>자녀 성적</h2>
      {picker}
      <Msg error={error} />
      {loading && <p>불러오는 중…</p>}
      {data && (
        <GradesView
          data={data}
          reportPath={(examId) =>
            `/bare/parent/grades/${examId}${studentId !== null ? `?student_id=${studentId}` : ""}`
          }
        />
      )}
    </section>
  );
}

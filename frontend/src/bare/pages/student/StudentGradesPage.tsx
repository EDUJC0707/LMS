/** 학생 성적 목록·추이 — GET /api/student/grades */
import { api } from "../../api";
import { Msg, useLoad } from "../../ui";
import GradesView from "../../views/GradesView";

export default function StudentGradesPage() {
  const { data, error, loading } = useLoad(
    async () => (await api.get("/student/grades")).data,
    [],
  );
  return (
    <section>
      <h2>내 성적</h2>
      <Msg error={error} />
      {loading && <p>불러오는 중…</p>}
      {data && (
        <GradesView data={data} reportPath={(examId) => `/bare/student/grades/${examId}`} />
      )}
    </section>
  );
}

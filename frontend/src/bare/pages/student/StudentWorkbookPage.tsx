/** 학생 워크북 열람 — GET /api/student/workbook */
import { api } from "../../api";
import { Msg, useLoad } from "../../ui";
import WorkbookView from "../../views/WorkbookView";

export default function StudentWorkbookPage() {
  const { data, error, loading } = useLoad(
    async () => (await api.get("/student/workbook")).data,
    [],
  );
  return (
    <section>
      <h2>내 워크북 사진</h2>
      <Msg error={error} />
      {loading && <p>불러오는 중…</p>}
      {data && <WorkbookView data={data} />}
    </section>
  );
}

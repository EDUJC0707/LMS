/** 자녀 워크북 — GET /api/parent/workbook?student_id= */
import { api } from "../../api";
import { Msg, useLoad } from "../../ui";
import WorkbookView from "../../views/WorkbookView";
import { useChild } from "./common";

export default function ParentWorkbookPage() {
  const { studentId, picker } = useChild();
  const { data, error, loading } = useLoad(
    async () =>
      (
        await api.get("/parent/workbook", {
          params: studentId !== null ? { student_id: studentId } : {},
        })
      ).data,
    [studentId],
  );
  return (
    <section>
      <h2>자녀 워크북 사진</h2>
      {picker}
      <Msg error={error} />
      {loading && <p>불러오는 중…</p>}
      {data && <WorkbookView data={data} />}
    </section>
  );
}

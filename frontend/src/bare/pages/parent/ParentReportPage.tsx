/** 자녀 성적표 상세 — GET /api/parent/grades/{exam_id}?student_id= */
import { Link, useParams } from "react-router-dom";

import { api } from "../../api";
import { Msg, useLoad } from "../../ui";
import ReportView from "../../views/ReportView";
import { useChild } from "./common";

export default function ParentReportPage() {
  const { examId } = useParams();
  const { studentId, picker } = useChild();
  const { data, error, loading } = useLoad(
    async () =>
      (
        await api.get(`/parent/grades/${examId}`, {
          params: studentId !== null ? { student_id: studentId } : {},
        })
      ).data,
    [examId, studentId],
  );
  return (
    <section>
      <h2>
        자녀 성적표 상세 <Link to="/bare/parent/grades">(목록으로)</Link>
      </h2>
      {picker}
      <Msg error={error} />
      {loading && <p>불러오는 중…</p>}
      {data && <ReportView data={data} />}
    </section>
  );
}

/** 학생 성적표 상세 — GET /api/student/grades/{exam_id} */
import { Link, useParams } from "react-router-dom";

import { api } from "../../api";
import { Msg, useLoad } from "../../ui";
import ReportView from "../../views/ReportView";

export default function StudentReportPage() {
  const { examId } = useParams();
  const { data, error, loading } = useLoad(
    async () => (await api.get(`/student/grades/${examId}`)).data,
    [examId],
  );
  return (
    <section>
      <h2>
        성적표 상세 <Link to="/bare/student/grades">(목록으로)</Link>
      </h2>
      <Msg error={error} />
      {loading && <p>불러오는 중…</p>}
      {data && <ReportView data={data} />}
    </section>
  );
}

/**
 * 자녀 성적표 상세 — GET /api/parent/grades/{exam_id}?student_id=
 *
 * 미응시 회차는 서버가 report 를 만들지 않는다(PRD 3.1.1) — 빈 성적표를
 * 지어내지 않고 왜 없는지만 알린다.
 */
import { Link, useParams } from "react-router-dom";

import { http, useApi } from "../../api";
import { Alert, Card, EmptyState, ErrorState, Loading, PageHeader } from "../../components";
import { NO_CHILD_TITLE, useChild } from "./childContext";
import { GradeReportView } from "./GradeReportView";
import { dayLabel } from "./format";
import "./parent.css";
import { GradeReportPayload } from "./types";

export default function ParentGradeDetailPage() {
  const { examId } = useParams();
  const { studentId, picker } = useChild();

  const report = useApi<GradeReportPayload | null>(
    () =>
      studentId === null || !examId
        ? Promise.resolve(null)
        : http
            .get<GradeReportPayload>(`/parent/grades/${examId}`, {
              params: { student_id: studentId },
            })
            .then((response) => response.data),
    [studentId, examId],
  );

  const data = report.data;

  return (
    <>
      <PageHeader
        title="성적표"
        description={
          data
            ? `${data.exam.name} · ${dayLabel(data.exam.exam_date)}${
                data.exam.round_no === null ? "" : ` · ${data.exam.round_no}회차`
              }`
            : undefined
        }
        actions={
          <div className="parent-headactions">
            {picker}
            <Link to="/parent/grades">성적 목록</Link>
          </div>
        }
      />

      {studentId === null ? (
        <Card>
          <EmptyState title={NO_CHILD_TITLE} />
        </Card>
      ) : report.loading ? (
        <Loading />
      ) : report.error ? (
        <ErrorState description={report.error} onRetry={report.reload} />
      ) : data ? (
        <div className="ui-stack">
          {data.exam.notice && <Alert tone="info">{data.exam.notice}</Alert>}

          {data.report ? (
            <GradeReportView
              summary={data.report.summary}
              units={data.report.units}
              questions={data.report.questions}
              guides={data.report.wrong_answer_guides}
              themeTrends={data.report.theme_trends}
            />
          ) : (
            <Card>
              <EmptyState
                title="이 회차는 응시 기록이 없습니다"
                action={<Link to="/parent/grades">다른 회차 보기</Link>}
              />
            </Card>
          )}
        </div>
      ) : null}
    </>
  );
}

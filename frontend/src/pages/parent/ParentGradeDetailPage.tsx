/**
 * 자녀 성적표 상세 — GET /api/parent/grades/{exam_id}?student_id=
 *
 * 미응시 회차는 서버가 report 를 만들지 않는다(PRD 3.1.1) — 빈 성적표를
 * 지어내지 않고 왜 없는지만 알린다.
 */
import { Link, useParams } from "react-router-dom";

import { http, useApi } from "../../api";
import { Alert, Card, EmptyState, ErrorState, Loading, ScopeBar } from "../../components";
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

  // 상단바는 레일 라벨인 "성적"만 말한다 — 어느 회차의 누구 성적표인지는
  // 본문 첫 카드가 들고 있어야 한다(제목=시험 이름, aside=회차·응시일·자녀).
  const identity = data
    ? [
        data.exam.round_no === null ? null : `${data.exam.round_no}회`,
        dayLabel(data.exam.exam_date),
        data.student.name,
        `원번 ${data.student.login_id ?? data.student.matching_key}`,
      ]
        .filter(Boolean)
        .join(" · ")
    : "";

  return (
    <>
      {picker && <ScopeBar>{picker}</ScopeBar>}

      {studentId === null ? (
        <Card padding="none">
          <EmptyState title={NO_CHILD_TITLE} />
        </Card>
      ) : report.loading ? (
        <Loading label="성적표를 불러오는 중…" />
      ) : report.error ? (
        <ErrorState description={report.error} onRetry={report.reload} />
      ) : data ? (
        <div className="ui-stack">
          {data.exam.notice && <Alert tone="info">{data.exam.notice}</Alert>}

          {data.report ? (
            <GradeReportView
              examName={data.exam.name}
              identity={identity}
              summary={data.report.summary}
              units={data.report.units}
              questions={data.report.questions}
              guides={data.report.wrong_answer_guides}
              themeTrends={data.report.theme_trends}
            />
          ) : (
            <Card title={data.exam.name} aside={identity} padding="none">
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

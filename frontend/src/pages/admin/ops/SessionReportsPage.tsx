/**
 * 성적표 인쇄 — 그 회차 시험의 성적표를 명단 순서로 쌓는다.
 *
 * 호출: GET /api/admin/attendance/sessions/{id}/reports[?student_id=]
 *
 * 반 일괄과 개별이 **같은 화면**이다(FLOW 3-11 "반 전체 일괄 프린트와 학생
 * 하나만 프린트가 둘 다 된다") — 쿼리로 명단을 좁힐 뿐 그리는 코드는 하나다.
 * 본문은 학생이 보는 것과 같은 컴포넌트로 그린다(GradeReportBody).
 *
 * 인쇄는 브라우저가 한다 — `window.print()`. 학생마다 새 장에서 시작하는 것은
 * `.st-sheet` 의 break-after(student.css @media print) 가 맡는다.
 */
import { useParams, useSearchParams } from "react-router-dom";

import { http, useApi } from "../../../api";
import { Alert, Button, EmptyState, ErrorState, Loading } from "../../../components";
import { GradeReportBody } from "../../student/GradeReportBody";
import { GradeReport, reportIdentity } from "../../student/lib";

export default function SessionReportsPage() {
  const { sessionId } = useParams();
  const [params] = useSearchParams();
  const studentId = params.get("student_id");

  const reports = useApi(
    async () =>
      (
        await http.get<{ reports: GradeReport[] }>(
          `/admin/attendance/sessions/${sessionId}/reports`,
          { params: studentId ? { student_id: studentId } : undefined },
        )
      ).data.reports,
    [sessionId, studentId],
  );

  if (reports.loading) {
    return <Loading label="성적표를 불러오는 중…" />;
  }

  if (reports.error || !reports.data) {
    return <ErrorState description={reports.error ?? undefined} onRetry={reports.reload} />;
  }

  if (reports.data.length === 0) {
    return <EmptyState title="성적표가 있는 학생이 없습니다" />;
  }

  return (
    // `ui-stack` 은 flex 다. flex 아이템 사이의 강제 개행은 엔진마다 구현이 갈려
    // 한 장에 두 명이 겹쳐 나올 수 있다 — 인쇄 대상 목록은 평범한 블록으로 둔다.
    <div className="op-print-sheets">
      <div className="ui-row st-noprint">
        <Button variant="primary" onClick={() => window.print()}>
          인쇄
        </Button>
      </div>
      {/* 서버가 성적 없는·미응시 학생을 이미 뺐다 — 빈 장을 끼우지 않는다. */}
      {reports.data.map(({ student, exam, report: body }) =>
        body ? (
          <article key={student.student_id} className="st-sheet">
            {/* 공지사항은 지면에도 실린다(PRD 3.1.1·3.2.1) — 배부 전에 적는 값이라
                종이가 그 자리다. 한 장에 한 명이므로 학생마다 한 번 나온다. */}
            {exam.notice && <Alert tone="info">{exam.notice}</Alert>}
            <GradeReportBody
              examName={exam.name}
              identity={reportIdentity(exam, student)}
              summary={body.summary}
              units={body.units}
              questions={body.questions}
              guides={body.wrong_answer_guides}
              themeTrends={body.theme_trends}
            />
          </article>
        ) : null,
      )}
    </div>
  );
}

/**
 * 학생 성적표 상세 — GET /api/student/grades/{exam_id} (PRD 3.2.1 전 섹션)
 *
 * 본문은 GradeReportBody 가 그린다 — 관리자가 지면으로 뽑는 것과 **같은
 * 컴포넌트**다(FLOW 3-11 "LMS 에 들어가서 보는 것과 같은 화면").
 * 이 파일에 남은 것은 조회·미응시 분기와, 이 회차에만 붙는 시험 안내다.
 * 인쇄를 고려해 카드는 페이지 넘김에서 쪼개지지 않게 했다(student.css @media print).
 */
import { Link, useParams } from "react-router-dom";

import { http, useApi } from "../../api";
import { Alert, Card, EmptyState, ErrorState, Loading } from "../../components";
import { GradeReportBody } from "./GradeReportBody";
import { GradeReport, reportIdentity } from "./lib";

export default function StudentGradeDetailPage() {
  const { examId } = useParams();
  const report = useApi(
    () => http.get<GradeReport>(`/student/grades/${examId}`).then((r) => r.data),
    [examId],
  );

  if (report.loading) {
    return <Loading label="성적표를 불러오는 중…" />;
  }

  if (report.error || !report.data) {
    return <ErrorState description={report.error ?? undefined} onRetry={report.reload} />;
  }

  const { exam, student, is_taken: isTaken, report: body } = report.data;
  // 상단바는 "성적"만 말한다(레일 라벨). 어느 회차의 누구 성적표인지는 첫 카드가
  // 들고 있어야 한다 — 인쇄하면 상단바가 빠지기 때문(student.css @media print).
  const identity = reportIdentity(exam, student);

  if (!isTaken || !body) {
    return (
      // 빈 상태는 제 여백(48px)을 갖고 있다 — 카드 여백을 겹쳐 얹지 않는다.
      <Card title={exam.name} aside={identity} padding="none">
        <EmptyState
          title="이 회차는 응시 기록이 없어 성적표가 없습니다"
          action={<Link to="/student/grades">다른 회차 보기</Link>}
        />
      </Card>
    );
  }

  return (
    <div className="ui-stack">
      {exam.notice && <Alert tone="info">{exam.notice}</Alert>}
      <GradeReportBody
        examName={exam.name}
        identity={identity}
        summary={body.summary}
        units={body.units}
        questions={body.questions}
        guides={body.wrong_answer_guides}
        themeTrends={body.theme_trends}
      />
    </div>
  );
}

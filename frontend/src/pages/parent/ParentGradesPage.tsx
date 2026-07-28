/**
 * 자녀 성적 목록 — GET /api/parent/grades?student_id=
 *
 * 시험별 결과와 회차 추이를 보여 준다. 미응시 회차는 성적표를 만들지 않으므로
 * 상세 링크 대신 상태만 표시한다(PRD 3.1.1·§4 상태 기반 노출).
 */
import { Link } from "react-router-dom";

import { http, useApi } from "../../api";
import {
  Badge,
  Card,
  EmptyState,
  ErrorState,
  Loading,
  PageHeader,
  Table,
} from "../../components";
import { NO_CHILD_DESC, NO_CHILD_TITLE, useChild } from "./childContext";
import { score, shortDay } from "./format";
import "./parent.css";
import { GradeList } from "./types";

export default function ParentGradesPage() {
  const { studentId, picker } = useChild();

  const grades = useApi<GradeList | null>(
    () =>
      studentId === null
        ? Promise.resolve(null)
        : http
            .get<GradeList>("/parent/grades", { params: { student_id: studentId } })
            .then((response) => response.data),
    [studentId],
  );

  const student = grades.data?.student;

  return (
    <>
      <PageHeader
        title="자녀 성적"
        description="지금까지 본 시험 결과와 회차별 추이입니다. 채점과 성적 입력은 학원에서 합니다."
        actions={picker}
      />

      {studentId === null ? (
        <Card>
          <EmptyState title={NO_CHILD_TITLE} description={NO_CHILD_DESC} />
        </Card>
      ) : grades.loading ? (
        <Loading />
      ) : grades.error ? (
        <ErrorState description={grades.error} onRetry={grades.reload} />
      ) : grades.data && student ? (
        <div className="ui-stack">
          <Card
            title={`${student.name}${student.current_class ? ` · ${student.current_class}` : ""}`}
            aside={
              <>
                원번 <span className="num">{student.unique_id}</span>
                {student.school ? ` · ${student.school}` : ""}
              </>
            }
            padding="none"
          >
            <Table
              rows={grades.data.exams}
              rowKey={(row) => row.exam_id}
              caption="시험별 결과"
              empty="아직 응시한 시험이 없습니다. 시험을 보면 결과가 여기에 쌓입니다."
              columns={[
                {
                  key: "round",
                  header: "회차",
                  width: "4.5rem",
                  numeric: true,
                  align: "left",
                  cell: (row) => (row.round_no === null ? "—" : `${row.round_no}회`),
                },
                {
                  key: "name",
                  header: "시험",
                  cell: (row) => (
                    <>
                      <div>{row.name}</div>
                      <div className="parent-note">{shortDay(row.exam_date)}</div>
                    </>
                  ),
                  sortValue: (row) => row.exam_date,
                },
                {
                  key: "myScore",
                  header: "점수",
                  align: "right",
                  numeric: true,
                  width: "7rem",
                  sortValue: (row) => row.my_score ?? -1,
                  cell: (row) =>
                    row.is_taken ? (
                      <>
                        {score(row.my_score)}
                        <span className="parent-note"> / {score(row.max_score)}</span>
                      </>
                    ) : (
                      "—"
                    ),
                },
                {
                  key: "average",
                  header: "전체 평균",
                  align: "right",
                  numeric: true,
                  width: "6.5rem",
                  cell: (row) => score(row.average),
                },
                {
                  key: "report",
                  header: "성적표",
                  width: "7.5rem",
                  cell: (row) =>
                    row.is_taken ? (
                      <Link to={`/parent/grades/${row.exam_id}`}>성적표 보기</Link>
                    ) : (
                      <Badge tone="outline">미응시</Badge>
                    ),
                },
              ]}
            />
          </Card>

          <Card title="회차별 추이" padding="none">
            <Table
              rows={grades.data.trend}
              rowKey={(row) => row.exam_id}
              caption="회차별 점수·백분위 추이"
              empty="추이를 그릴 만큼 시험을 보지 않았습니다."
              columns={[
                {
                  key: "round",
                  header: "회차",
                  cell: (row) => (
                    <>
                      <div>{row.round_no === null ? row.name : `${row.round_no}회`}</div>
                      <div className="parent-note">{shortDay(row.exam_date)}</div>
                    </>
                  ),
                },
                {
                  key: "my",
                  header: "자녀 점수",
                  align: "right",
                  numeric: true,
                  cell: (row) => (row.is_taken ? score(row.my_score) : "미응시"),
                },
                {
                  key: "percentile",
                  header: "백분위",
                  align: "right",
                  numeric: true,
                  cell: (row) => (row.percentile === null ? "—" : score(row.percentile)),
                },
                {
                  key: "average",
                  header: "전체 평균",
                  align: "right",
                  numeric: true,
                  cell: (row) => score(row.average),
                },
                {
                  key: "top30",
                  header: "상위 30%",
                  align: "right",
                  numeric: true,
                  cell: (row) => score(row.top30_score),
                },
                {
                  key: "highest",
                  header: "최고점",
                  align: "right",
                  numeric: true,
                  cell: (row) => score(row.highest_score),
                },
              ]}
            />
            <p className="parent-note" style={{ padding: "var(--space-md)" }}>
              백분위는 같은 시험을 본 학생들 사이에서 자녀가 어디쯤인지 나타냅니다 — 숫자가 클수록
              앞선 성적입니다.
            </p>
          </Card>
        </div>
      ) : null}
    </>
  );
}

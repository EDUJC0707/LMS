/**
 * 학생 성적 목록 · 추이 — GET /api/student/grades (PRD 3.2.1 성적 현황)
 *
 * 차트는 외부 라이브러리 없이 인라인 SVG(./charts). 계열을 색으로 구분하지
 * 않고 초점(내 점수)만 액센트 실선으로 두고, 나머지는 참조선·밴드로 내린다.
 */
import { Link, useNavigate } from "react-router-dom";

import { http, useApi } from "../../api";
import { Badge, Card, ErrorState, Loading, PageHeader, Table } from "../../components";
import { ChartLegend, TrendChart, TrendDatum } from "./charts";
import { ExamRow, GradeList, num } from "./lib";
import "./student.css";

export default function StudentGradesPage() {
  const navigate = useNavigate();
  const grades = useApi(() => http.get<GradeList>("/student/grades").then((r) => r.data), []);

  if (grades.loading) {
    return (
      <>
        <PageHeader title="성적" />
        <Loading label="성적을 불러오는 중…" />
      </>
    );
  }

  if (grades.error || !grades.data) {
    return (
      <>
        <PageHeader title="성적" />
        <ErrorState description={grades.error ?? undefined} onRetry={grades.reload} />
      </>
    );
  }

  const { student, exams, trend } = grades.data;
  const taken = trend.filter((point) => point.is_taken && point.my_score !== null);
  const maxScore = exams.find((e) => e.max_score !== null)?.max_score ?? 100;
  const latest = taken.length > 0 ? taken[taken.length - 1] : null;
  const previous = taken.length > 1 ? taken[taken.length - 2] : null;

  const chartData: TrendDatum[] = trend.map((point) => ({
    label: point.round_no !== null ? `${point.round_no}회` : point.exam_date.slice(5),
    mine: point.is_taken ? point.my_score : null,
    average: point.average,
    top30: point.top30_score,
    highest: point.highest_score,
  }));

  const delta =
    latest && previous && latest.my_score !== null && previous.my_score !== null
      ? latest.my_score - previous.my_score
      : null;

  return (
    <>
      <PageHeader
        title="성적"
        description={`${student.name} · 원번 ${student.unique_id}${
          student.school ? ` · ${student.school}` : ""
        } — 지금까지 응시한 시험 결과와 점수 변화입니다.`}
      />

      <div className="ui-stack">
        {taken.length >= 2 ? (
          <Card title="점수 추이" aside={`${taken.length}회 응시`}>
            <TrendChart data={chartData} maxScore={maxScore} />
            <ChartLegend
              items={[
                { kind: "mine", label: "내 점수" },
                { kind: "average", label: "전체 평균" },
                { kind: "top30", label: "상위 30% 점수" },
                { kind: "highest", label: "최고점" },
                { kind: "band", label: "평균~최고점 구간" },
              ]}
            />
            {delta !== null && latest && (
              <p className="st-note" style={{ marginTop: "var(--space-md)" }}>
                직전 회차보다{" "}
                {delta === 0
                  ? "점수가 같습니다"
                  : `${num(Math.abs(delta))}점 ${delta > 0 ? "올랐습니다" : "내렸습니다"}`}
                {latest.percentile !== null ? ` · 이번 회차 백분위 ${num(latest.percentile)}` : ""}.
              </p>
            )}
          </Card>
        ) : latest ? (
          <Card title="이번 성적">
            <div className="st-stats">
              <div className="st-stat st-stat--lead">
                <p className="st-stat__label">내 점수</p>
                <p className="st-stat__value">
                  {num(latest.my_score)}
                  <span className="st-stat__unit"> / {num(latest.max_score)}</span>
                </p>
              </div>
              <div className="st-stat">
                <p className="st-stat__label">전체 평균</p>
                <p className="st-stat__value">{num(latest.average)}</p>
              </div>
              <div className="st-stat">
                <p className="st-stat__label">백분위</p>
                <p className="st-stat__value">{num(latest.percentile)}</p>
              </div>
            </div>
            <p className="st-note" style={{ marginTop: "var(--space-md)" }}>
              두 번째 시험부터 회차별 점수 변화를 그래프로 보여드립니다.
            </p>
          </Card>
        ) : null}

        <Card title="회차별 결과" aside={`${exams.length}회`} padding="none">
          <Table<ExamRow>
            rows={exams}
            rowKey={(row) => row.exam_id}
            caption="회차별 시험 결과"
            onRowClick={(row) => {
              if (row.is_taken) navigate(`/student/grades/${row.exam_id}`);
            }}
            empty="아직 응시한 시험이 없습니다. 시험을 보면 회차별 결과와 성적표가 여기에 쌓입니다."
            columns={[
              {
                key: "round",
                header: "회차",
                width: "5rem",
                numeric: true,
                align: "left",
                sortValue: (row) => row.round_no ?? 0,
                cell: (row) => (row.round_no !== null ? `${row.round_no}회` : "—"),
              },
              {
                key: "name",
                header: "시험",
                cell: (row) => (
                  <>
                    <span style={{ fontWeight: "var(--weight-medium)" }}>{row.name}</span>
                    <span
                      className="num"
                      style={{
                        display: "block",
                        fontSize: "var(--text-xs)",
                        color: "var(--color-muted)",
                      }}
                    >
                      {row.exam_date}
                    </span>
                  </>
                ),
              },
              {
                key: "score",
                header: "내 점수",
                align: "right",
                numeric: true,
                sortValue: (row) => row.my_score ?? -1,
                cell: (row) =>
                  row.is_taken ? (
                    <>
                      {num(row.my_score)}
                      <span style={{ color: "var(--color-muted)" }}> / {num(row.max_score)}</span>
                    </>
                  ) : (
                    <Badge tone="neutral">미응시</Badge>
                  ),
              },
              {
                key: "average",
                header: "전체 평균",
                align: "right",
                numeric: true,
                sortValue: (row) => row.average ?? -1,
                cell: (row) => num(row.average),
              },
              {
                key: "report",
                header: "성적표",
                align: "right",
                width: "8rem",
                cell: (row) =>
                  row.is_taken ? (
                    <Link to={`/student/grades/${row.exam_id}`}>자세히 보기</Link>
                  ) : (
                    <span style={{ color: "var(--color-neutral)" }}>—</span>
                  ),
              },
            ]}
          />
        </Card>
      </div>
    </>
  );
}

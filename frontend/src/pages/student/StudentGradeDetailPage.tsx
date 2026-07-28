/**
 * 학생 성적표 상세 — GET /api/student/grades/{exam_id} (PRD 3.2.1 전 섹션)
 *
 * 섹션 순서는 "결과 → 어디가 약한가 → 무엇을 할 것인가" 로 읽히게 배치했다:
 *   ① 성적 요약(+점수 위치)  ② 대단원별  ③ 문항 채점표
 *   ④ 오답 학습동선          ⑤ 테마별 누적 정답률 추이
 * 미응시면 report 가 null 로 온다 — 요약을 상상해 채우지 않는다.
 * 인쇄를 고려해 카드는 페이지 넘김에서 쪼개지지 않게 했다(student.css @media print).
 */
import { Link, useParams } from "react-router-dom";

import { http, useApi } from "../../api";
import {
  Alert,
  Badge,
  Card,
  DetailsPanel,
  EmptyState,
  ErrorState,
  Loading,
  PageHeader,
  Table,
} from "../../components";
import type { BadgeTone } from "../../components";
import { RateBar, Sparkline } from "./charts";
import {
  GradeReport,
  ReportQuestion,
  ReportUnit,
  ThemeTrend,
  WrongAnswerGuide,
  num,
} from "./lib";
import "./student.css";

const RESULT_TONE: Record<string, BadgeTone> = {
  정답: "success",
  오답: "danger",
  무응답: "warning",
};

export default function StudentGradeDetailPage() {
  const { examId } = useParams();
  const report = useApi(
    () => http.get<GradeReport>(`/student/grades/${examId}`).then((r) => r.data),
    [examId],
  );

  if (report.loading) {
    return (
      <>
        <PageHeader title="성적표" />
        <Loading label="성적표를 불러오는 중…" />
      </>
    );
  }

  if (report.error || !report.data) {
    return (
      <>
        <PageHeader title="성적표" />
        <ErrorState description={report.error ?? undefined} onRetry={report.reload} />
      </>
    );
  }

  const { exam, student, is_taken: isTaken, report: body } = report.data;
  const roundLabel = exam.round_no !== null ? `${exam.round_no}회 · ` : "";

  const header = (
    <PageHeader
      title={exam.name}
      description={`${roundLabel}${exam.exam_date} 응시 — ${student.name} · 원번 ${student.unique_id}`}
      actions={<Link to="/student/grades">성적 목록으로</Link>}
    />
  );

  if (!isTaken || !body) {
    return (
      <>
        {header}
        <Card>
          <EmptyState
            title="이 회차는 응시 기록이 없어 성적표가 없습니다"
            description="응시하지 않은 시험은 채점 결과가 만들어지지 않습니다. 다음 회차에 응시하면 문항별 결과와 학습동선이 이곳에 나옵니다."
            action={<Link to="/student/grades">다른 회차 보기</Link>}
          />
        </Card>
      </>
    );
  }

  const { summary, units, questions, wrong_answer_guides: guides, theme_trends: themes } = body;
  const pos = (value: number) =>
    `${Math.max(0, Math.min(100, (value / (summary.max_score || 100)) * 100))}%`;

  return (
    <>
      {header}

      <div className="ui-stack">
        {exam.notice && <Alert tone="info">{exam.notice}</Alert>}

        {/* ① 성적 요약 */}
        <Card title="성적 요약" aside={`만점 ${num(summary.max_score)}점`}>
          <div className="st-stats">
            <div className="st-stat st-stat--lead">
              <p className="st-stat__label">내 점수</p>
              <p className="st-stat__value">
                {num(summary.my_score)}
                <span className="st-stat__unit"> / {num(summary.max_score)}</span>
              </p>
            </div>
            <div className="st-stat">
              <p className="st-stat__label">백분위</p>
              <p className="st-stat__value">{num(summary.percentile)}</p>
            </div>
            <div className="st-stat">
              <p className="st-stat__label">전체 평균</p>
              <p className="st-stat__value">{num(summary.average)}</p>
            </div>
            <div className="st-stat">
              <p className="st-stat__label">상위 30%</p>
              <p className="st-stat__value">{num(summary.top30_score)}</p>
            </div>
            <div className="st-stat">
              <p className="st-stat__label">최고점</p>
              <p className="st-stat__value">{num(summary.highest_score)}</p>
            </div>
            <div className="st-stat">
              <p className="st-stat__label">표준편차</p>
              <p className="st-stat__value">{num(summary.stddev)}</p>
            </div>
          </div>

          <div className="st-scale">
            <div className="st-scale__track">
              <span
                className="st-scale__band"
                style={{
                  left: pos(summary.average),
                  width: `calc(${pos(summary.highest_score)} - ${pos(summary.average)})`,
                }}
              />
              <span className="st-scale__tick" style={{ left: pos(summary.top30_score) }} />
              <span className="st-scale__me" style={{ left: pos(summary.my_score) }} />
            </div>
            <div className="st-scale__legend">
              <span>
                내 점수 <b className="num">{num(summary.my_score)}</b>
              </span>
              <span>
                평균 <b className="num">{num(summary.average)}</b>
              </span>
              <span>
                상위 30% <b className="num">{num(summary.top30_score)}</b>
              </span>
              <span>
                최고점 <b className="num">{num(summary.highest_score)}</b>
              </span>
            </div>
          </div>
        </Card>

        {/* ② 대단원별 */}
        <Card title="대단원별 점수" aside={`${units.length}개 단원`} padding="none">
          <Table<ReportUnit>
            rows={units}
            rowKey={(row) => row.unit_major}
            caption="대단원별 점수와 정답률"
            empty="대단원 구분이 없는 시험입니다."
            columns={[
              { key: "unit", header: "대단원", cell: (row) => row.unit_major },
              {
                key: "count",
                header: "문항",
                align: "right",
                numeric: true,
                cell: (row) => `${row.question_count}문항`,
              },
              {
                key: "correct",
                header: "정답 / 오답",
                align: "right",
                numeric: true,
                cell: (row) => `${row.correct_count} / ${row.wrong_count}`,
              },
              {
                key: "points",
                header: "내 점수",
                align: "right",
                numeric: true,
                cell: (row) => `${num(row.my_points)} / ${num(row.unit_max_points)}`,
              },
              {
                key: "rate",
                header: "정답률",
                width: "15rem",
                sortValue: (row) => row.correct_rate,
                cell: (row) => (
                  <span className="st-cell-rate">
                    <RateBar rate={row.correct_rate} caption={`${row.unit_major} 정답률`} />
                    <b className="num">{num(row.correct_rate)}%</b>
                  </span>
                ),
              },
            ]}
          />
        </Card>

        {/* ③ 문항 채점표 */}
        <Card
          title="문항 채점표"
          aside={`${questions.length}문항`}
          padding="none"
        >
          <Table<ReportQuestion>
            rows={questions}
            rowKey={(row) => row.q_number}
            dense
            caption="문항별 채점 결과"
            empty="채점된 문항이 없습니다."
            columns={[
              {
                key: "no",
                header: "번호",
                width: "4.5rem",
                numeric: true,
                align: "left",
                cell: (row) => row.q_number,
              },
              {
                key: "unit",
                header: "단원",
                cell: (row) => (
                  <>
                    {row.unit_major}
                    {row.unit_minor && (
                      <span style={{ color: "var(--color-muted)" }}> · {row.unit_minor}</span>
                    )}
                  </>
                ),
              },
              {
                key: "points",
                header: "배점",
                align: "right",
                numeric: true,
                cell: (row) => num(row.points),
              },
              {
                key: "answer",
                header: "정답",
                align: "center",
                numeric: true,
                cell: (row) => row.answer,
              },
              {
                key: "marked",
                header: "내 답",
                align: "center",
                numeric: true,
                cell: (row) => row.marked ?? "—",
              },
              {
                key: "result",
                header: "결과",
                align: "center",
                width: "6rem",
                cell: (row) =>
                  row.result ? (
                    <Badge tone={RESULT_TONE[row.result] ?? "neutral"}>{row.result}</Badge>
                  ) : (
                    "—"
                  ),
              },
              {
                key: "wrong",
                header: "전체 오답률",
                align: "right",
                numeric: true,
                sortValue: (row) => row.wrong_rate ?? -1,
                cell: (row) => (row.wrong_rate === null ? "—" : `${num(row.wrong_rate)}%`),
              },
            ]}
          />
        </Card>

        {/* ④ 오답 학습동선 */}
        <Card title="오답 문항 학습동선" aside={guides.length > 0 ? `${guides.length}문항` : undefined}>
          {guides.length === 0 ? (
            <EmptyState
              title="틀린 문항이 없습니다"
              description="이번 회차는 복습할 오답이 없어 학습동선을 만들지 않았습니다."
            />
          ) : (
            <div className="st-guides">
              {guides.map((guide: WrongAnswerGuide) => (
                <div key={guide.q_number} className="st-guide">
                  <span className="st-guide__no">{guide.q_number}번</span>
                  <span className="st-guide__where">
                    {guide.unit_major}
                    {guide.theme_tag ? ` · ${guide.theme_tag}` : ""}
                  </span>
                  <span className="st-guide__text">{guide.study_guide}</span>
                  {guide.guide_video && (
                    <span className="st-guide__video">
                      <Badge tone="outline">가이드 영상</Badge>
                      {guide.guide_video.title}
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}
        </Card>

        {/* ⑤ 테마별 누적 정답률 */}
        <Card title="테마별 누적 정답률" aside={themes.length > 0 ? `${themes.length}개 테마` : undefined}>
          {themes.length === 0 ? (
            <EmptyState
              title="테마가 붙은 문항이 아직 없습니다"
              description="문항에 테마가 지정되면 회차가 쌓일수록 테마별 누적 정답률을 보여드립니다."
            />
          ) : (
            <div className="st-weeks">
              {themes.map((trend: ThemeTrend) => {
                const last = trend.points[trend.points.length - 1];
                return (
                  <DetailsPanel
                    key={trend.theme}
                    summary={
                      <span className="st-theme">
                        <span className="st-theme__name">{trend.theme}</span>
                        <Sparkline
                          values={trend.points.map((p) => p.cumulative_rate)}
                          label={`${trend.theme} 누적 정답률 추이`}
                        />
                      </span>
                    }
                    aside={last ? `누적 ${num(last.cumulative_rate)}%` : undefined}
                  >
                    <Table
                      rows={trend.points}
                      rowKey={(row) => row.exam_id}
                      dense
                      caption={`${trend.theme} 회차별 정답률`}
                      empty="아직 이 테마의 응시 기록이 없습니다."
                      columns={[
                        {
                          key: "round",
                          header: "회차",
                          cell: (row) =>
                            `${row.round_no !== null ? `${row.round_no}회` : "—"} (${row.exam_date})`,
                        },
                        {
                          key: "correct",
                          header: "이번 회차",
                          align: "right",
                          numeric: true,
                          cell: (row) => `${row.correct} / ${row.total}`,
                        },
                        {
                          key: "rate",
                          header: "회차 정답률",
                          align: "right",
                          numeric: true,
                          cell: (row) => `${num(row.rate)}%`,
                        },
                        {
                          key: "cum",
                          header: "누적 정답률",
                          align: "right",
                          numeric: true,
                          cell: (row) => `${num(row.cumulative_rate)}%`,
                        },
                      ]}
                    />
                  </DetailsPanel>
                );
              })}
            </div>
          )}
        </Card>
      </div>
    </>
  );
}

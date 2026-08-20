/**
 * 성적표 본문 — GET /api/parent/grades/{exam_id} 의 report 블록을 그린다.
 *
 * 학부모가 보는 순서대로 쌓는다: 총평 → 단원별 → 오답 학습동선 →
 * (접어 둔) 문항 채점표 → (접어 둔) 테마별 누적 정답률.
 * 서버가 report 를 안 준 회차(미응시)는 이 컴포넌트를 부르지 않는다.
 */
import { Badge, Card, DetailsPanel, EmptyState, Table } from "../../components";
import { score, shortDay } from "./format";
import "./parent.css";
import {
  ReportGuide,
  ReportQuestion,
  ReportSummary,
  ReportUnit,
  ReportUnitMinor,
  ThemeTrend,
} from "./types";

export interface GradeReportViewProps {
  /** 첫 카드 제목 — 시험 이름. 상단바는 "성적"만 말하므로 본문이 들고 있어야 한다. */
  examName: string;
  /** 첫 카드 aside — 회차·응시일·자녀 이름·원번. */
  identity: string;
  summary: ReportSummary;
  units: ReportUnit[];
  questions: ReportQuestion[];
  guides: ReportGuide[];
  themeTrends: ThemeTrend[];
}

export function GradeReportView({
  examName,
  identity,
  summary,
  units,
  questions,
  guides,
  themeTrends,
}: GradeReportViewProps) {
  return (
    <div className="ui-stack">
      {/* 옛 "총평" 라벨 대신 시험 이름이 제목이 된다 — 표 내용이 곧 총평이다. */}
      <Card title={examName} aside={identity}>
        <dl className="parent-facts">
          <div>
            <dt className="parent-facts__term">받은 점수</dt>
            <dd className="parent-facts__value parent-facts__value--strong">
              <span className="num">{score(summary.my_score)}</span>
              <span className="parent-note"> / {score(summary.max_score)}</span>
            </dd>
          </div>
          <div>
            <dt className="parent-facts__term">전체 평균</dt>
            <dd className="parent-facts__value num">{score(summary.average)}</dd>
          </div>
          <div>
            <dt className="parent-facts__term">백분위</dt>
            <dd className="parent-facts__value num">{score(summary.percentile)}</dd>
          </div>
          <div>
            <dt className="parent-facts__term">상위 30% 점수</dt>
            <dd className="parent-facts__value num">{score(summary.top30_score)}</dd>
          </div>
          <div>
            <dt className="parent-facts__term">최고점</dt>
            <dd className="parent-facts__value num">{score(summary.highest_score)}</dd>
          </div>
          <div>
            <dt className="parent-facts__term">표준편차</dt>
            <dd className="parent-facts__value num">{score(summary.stddev)}</dd>
          </div>
        </dl>
      </Card>

      {/* 중단원은 자기 대단원 바로 밑에 들여쓴다(FLOW 4-3) */}
      <Card title="단원별 점수" padding="none">
        <Table<ReportUnit | ReportUnitMinor>
          rows={units.flatMap((unit) => [unit, ...unit.minors])}
          rowKey={(row) =>
            "unit_minor" in row ? `${row.unit_major}/${row.unit_minor}` : row.unit_major
          }
          caption="단원별 점수와 정답률"
          empty="이 시험에는 단원이 나뉘어 있지 않습니다"
          columns={[
            {
              key: "unit",
              header: "단원",
              cell: (row) =>
                "unit_minor" in row ? (
                  <span className="parent-unit-minor">{row.unit_minor}</span>
                ) : (
                  row.unit_major
                ),
            },
            {
              key: "count",
              header: "문항",
              align: "right",
              numeric: true,
              cell: (row) => row.question_count,
            },
            {
              key: "correct",
              header: "맞은 문항",
              align: "right",
              numeric: true,
              cell: (row) => `${row.correct_count} / ${row.question_count}`,
            },
            {
              key: "points",
              header: "점수",
              align: "right",
              numeric: true,
              cell: (row) => `${score(row.my_points)} / ${score(row.unit_max_points)}`,
            },
            {
              key: "rate",
              header: "정답률",
              align: "right",
              numeric: true,
              // 정렬을 열지 않는다 — 행이 대단원·중단원 두 층이라 섞어 세우면
              // 중단원이 자기 대단원에서 떨어져 나간다.
              cell: (row) => `${score(row.correct_rate)}%`,
            },
          ]}
        />
      </Card>

      <Card
        title="틀린 문항과 다음 학습"
        aside={guides.length > 0 ? `${guides.length}문항` : undefined}
        padding="none"
      >
        {guides.length === 0 ? (
          <EmptyState title="틀린 문항이 없습니다" />
        ) : (
          <Table
            rows={guides}
            rowKey={(row) => row.q_number}
            caption="오답 문항별 학습 안내"
            columns={[
              {
                key: "q",
                header: "문항",
                width: "4.5rem",
                numeric: true,
                align: "left",
                cell: (row) => `${row.q_number}번`,
              },
              {
                key: "unit",
                header: "단원",
                width: "11rem",
                cell: (row) => (
                  <>
                    <div>{row.unit_major}</div>
                    {row.theme_tag && <div className="parent-note">{row.theme_tag}</div>}
                  </>
                ),
              },
              {
                key: "guide",
                header: "학습 안내",
                cell: (row) => (
                  <p className="parent-guide">
                    {row.study_guide}
                    {row.guide_video && (
                      <span className="parent-guide__video">
                        복습 영상 — {row.guide_video.title}
                      </span>
                    )}
                  </p>
                ),
              },
            ]}
          />
        )}
      </Card>

      <DetailsPanel summary="문항별 채점표" aside={`${questions.length}문항`}>
        <Table
          rows={questions}
          rowKey={(row) => row.q_number}
          dense
          caption="문항별 정답·자녀 답안·결과"
          empty="문항 정보가 아직 등록되지 않았습니다"
          columns={[
            {
              key: "q",
              header: "번호",
              width: "3.5rem",
              numeric: true,
              align: "left",
              cell: (row) => row.q_number,
            },
            {
              key: "unit",
              header: "단원",
              cell: (row) => (
                <>
                  <div>{row.unit_major}</div>
                  {row.unit_minor && <div className="parent-note">{row.unit_minor}</div>}
                </>
              ),
            },
            {
              key: "points",
              header: "배점",
              align: "right",
              numeric: true,
              cell: (row) => score(row.points),
            },
            { key: "answer", header: "정답", numeric: true, align: "center", cell: (row) => row.answer },
            {
              key: "marked",
              header: "자녀 답",
              numeric: true,
              align: "center",
              cell: (row) => row.marked ?? "—",
            },
            {
              key: "result",
              header: "결과",
              width: "6rem",
              cell: (row) =>
                row.result === "정답" ? (
                  <Badge tone="success">정답</Badge>
                ) : row.result === "오답" ? (
                  <Badge tone="danger">오답</Badge>
                ) : row.result ? (
                  <Badge tone="warning">{row.result}</Badge>
                ) : (
                  "—"
                ),
            },
            {
              key: "wrongRate",
              header: "전체 오답률",
              align: "right",
              numeric: true,
              cell: (row) => (row.wrong_rate === null ? "—" : `${score(row.wrong_rate)}%`),
            },
          ]}
        />
      </DetailsPanel>

      {/* 비어 있으면 EmptyState 가 자기 여백을 갖는다 — 카드 패딩을 겹쳐 주면
          한 줄짜리 안내가 72px 안쪽에 갇힌다(다른 빈 카드와 값이 어긋난다). */}
      <Card
        title="주제별 누적 정답률"
        aside={themeTrends.length > 0 ? `${themeTrends.length}개 주제` : undefined}
        padding={themeTrends.length === 0 ? "none" : "md"}
      >
        {themeTrends.length === 0 ? (
          <EmptyState title="아직 주제별로 쌓인 기록이 없습니다" />
        ) : (
          <div className="ui-stack ui-stack--sm">
            {themeTrends.map((trend) => {
              const last = trend.points[trend.points.length - 1];
              return (
                <DetailsPanel
                  key={trend.theme}
                  summary={trend.theme}
                  aside={last ? `누적 정답률 ${score(last.cumulative_rate)}%` : undefined}
                >
                  <Table
                    rows={trend.points}
                    rowKey={(row) => row.exam_id}
                    dense
                    caption={`${trend.theme} 회차별 정답률`}
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
                        key: "correct",
                        header: "맞은 문항",
                        align: "right",
                        numeric: true,
                        cell: (row) => `${row.correct} / ${row.total}`,
                      },
                      {
                        key: "rate",
                        header: "회차 정답률",
                        align: "right",
                        numeric: true,
                        cell: (row) => `${score(row.rate)}%`,
                      },
                      {
                        key: "cumulative",
                        header: "누적 정답률",
                        align: "right",
                        numeric: true,
                        cell: (row) => `${score(row.cumulative_rate)}%`,
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
  );
}

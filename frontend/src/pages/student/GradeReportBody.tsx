/**
 * 성적표 본문 — 학생 화면과 관리자 인쇄 지면이 함께 쓰는 렌더러.
 *
 * 섹션 순서는 "결과 → 어디가 약한가 → 무엇을 할 것인가" 로 읽히게 배치했다:
 *   ① 성적 요약(+점수 위치)  ② 대단원별  ③ 문항 채점표
 *   ④ 오답 학습동선          ⑤ 테마별 누적 정답률 추이
 *
 * 미응시(report=null)면 호출부가 이 컴포넌트를 부르지 않는다 — 요약을
 * 상상해 채우지 않는다.
 *
 * **시험 안내(exam.notice)는 여기 없다.** 회차마다 하나뿐인 문구라 반 일괄
 * 인쇄에 넣으면 30장에 30번 찍힌다 — 학생 화면이 본문 위에 따로 얹는다.
 *
 * `./student.css` 를 여기서 import 하는 것이 인쇄 스타일을 관리자 화면까지
 * 데려가는 통로다(@media print).
 */
import { Link } from "react-router-dom";

import {
  Badge,
  Card,
  DetailsPanel,
  EmptyState,
  Table,
} from "../../components";
import type { BadgeTone } from "../../components";
import { RateBar, Sparkline } from "./charts";
import {
  ReportQuestion,
  ReportSummary,
  ReportUnit,
  ReportUnitMinor,
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

export interface GradeReportBodyProps {
  /** 첫 카드 제목 — 시험 이름. 상단바는 "성적"만 말하고 인쇄하면 그마저 빠진다. */
  examName: string;
  /** 첫 카드 aside — 회차·응시일·이름·원번(lib.reportIdentity). */
  identity: string;
  summary: ReportSummary;
  units: ReportUnit[];
  questions: ReportQuestion[];
  guides: WrongAnswerGuide[];
  themeTrends: ThemeTrend[];
}

export function GradeReportBody({
  examName,
  identity,
  summary,
  units,
  questions,
  guides,
  themeTrends: themes,
}: GradeReportBodyProps) {
  const pos = (value: number) =>
    `${Math.max(0, Math.min(100, (value / (summary.max_score || 100)) * 100))}%`;

  return (
    <div className="ui-stack">
      {/* ① 성적 요약 — 카드 제목이 곧 이 성적표가 무엇인지다(만점은 아래 내 점수 옆에 있다) */}
      <Card title={examName} aside={identity}>
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

      {/* ② 대단원·중단원별 — 중단원은 자기 대단원 바로 밑에 들여쓴다(FLOW 4-3) */}
      <Card title="단원별 점수" padding="none">
        <Table<ReportUnit | ReportUnitMinor>
          rows={units.flatMap((unit) => [unit, ...unit.minors])}
          rowKey={(row) =>
            "unit_minor" in row ? `${row.unit_major}/${row.unit_minor}` : row.unit_major
          }
          caption="단원별 점수와 정답률"
          empty="단원 구분이 없는 시험입니다"
          columns={[
            {
              key: "unit",
              header: "단원",
              cell: (row) =>
                "unit_minor" in row ? (
                  <span className="st-unit-minor">{row.unit_minor}</span>
                ) : (
                  row.unit_major
                ),
            },
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
          empty="채점된 문항이 없습니다"
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
      <Card
        title="오답 문항 학습동선"
        aside={guides.length > 0 ? `${guides.length}문항` : undefined}
        padding={guides.length === 0 ? "none" : "md"}
      >
        {guides.length === 0 ? (
          <EmptyState title="틀린 문항이 없습니다" />
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
                  <Link
                    className="st-guide__video"
                    to={`/student/videos/${guide.guide_video.video_id}`}
                  >
                    <Badge tone="outline">가이드 영상</Badge>
                    {guide.guide_video.title}
                  </Link>
                )}
              </div>
            ))}
          </div>
        )}
      </Card>

      {/* ⑤ 테마별 누적 정답률 */}
      <Card
        title="테마별 누적 정답률"
        aside={themes.length > 0 ? `${themes.length}개 테마` : undefined}
        padding={themes.length === 0 ? "none" : "md"}
      >
        {themes.length === 0 ? (
          <EmptyState title="테마가 붙은 문항이 아직 없습니다" />
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
                    empty="아직 이 테마의 응시 기록이 없습니다"
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
  );
}

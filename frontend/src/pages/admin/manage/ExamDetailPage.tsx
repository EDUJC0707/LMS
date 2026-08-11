/**
 * /admin/exams/:examId — 한 회차의 학생별 점수 · 문항 분석.
 *
 * API  GET /api/admin/exams/{exam_id}
 *      → {exam, stats, students[], questions[]}
 *
 * 화면 설계
 * - 위: 서버가 준 통계만 한 줄로(평균·표준편차·최고·상위 30%). 만들어낸 수치 없음.
 * - 학생 표: 석차순이 기본. 제출/미제출을 탭으로 갈라 놓는 이유는 미제출자가
 *   섞여 있으면 평균·석차를 잘못 읽기 때문이다.
 *   "미응시"가 아니라 "시험 미제출"인 근거: 판정 근거가 OMR 카드가 들어왔는가
 *   (scores.is_taken)이고, 수업 초반 시험이라 늦게 온 학생은 앉아 있었어도
 *   카드를 못 낸다 — 관측한 사실 그대로 부른다(2026-07-29 값집합 개편).
 * - 문항 표: 정답률이 낮은 문항이 곧 다음 수업의 재료라 정답률 정렬을 붙이고
 *   40% 미만에는 표시를 남긴다(기준은 색이 아니라 라벨로도 읽힌다).
 */
import { useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { http, useApi } from "../../../api";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  Field,
  Input,
  Loading,
  StatusBadge,
  Table,
  Tabs,
} from "../../../components";
import AnswerKeyPanel from "./AnswerKeyPanel";
import SheetUploadPanel from "./SheetUploadPanel";
import { score } from "./ExamsPage";
import "./manage.css";
import type { ExamDetail, ExamQuestionRow, ExamStudentRow } from "./types";

type TakenTab = "제출" | "미제출" | "전체";

export default function ExamDetailPage() {
  const { examId } = useParams();
  const navigate = useNavigate();
  const detail = useApi(
    () => http.get<ExamDetail>(`/admin/exams/${examId}`).then((r) => r.data),
    [examId],
  );

  const [tab, setTab] = useState<TakenTab>("제출");
  const [query, setQuery] = useState("");

  const students = useMemo(() => {
    const list = detail.data?.students ?? [];
    const needle = query.trim();
    return list.filter((student) => {
      if (tab === "제출" && !student.is_taken) return false;
      if (tab === "미제출" && student.is_taken) return false;
      if (!needle) return true;
      return student.name.includes(needle) || (student.login_id ?? "").includes(needle);
    });
  }, [detail.data, tab, query]);

  const takenCount = (detail.data?.students ?? []).filter((s) => s.is_taken).length;
  const missingCount = (detail.data?.students ?? []).length - takenCount;

  if (detail.loading) return <Loading label="시험 결과를 불러오는 중…" />;

  if (detail.error || !detail.data) {
    return <ErrorState description={detail.error ?? undefined} onRetry={detail.reload} />;
  }

  const { exam, stats, questions } = detail.data;

  return (
    <div className="ui-stack">
      {/* 상단바는 "시험·성적"까지만 말한다 — 어느 회차인지는 첫 카드가 든다. */}
      <Card
        title={exam.name}
        aside={
          <div className="pm-review__nav">
            <StatusBadge status={stats.processing_status} />
            <Button size="sm" onClick={() => navigate("sheets")}>
              스캔 보정
            </Button>
          </div>
        }
      >
        <div className="ui-stack ui-stack--md">
          <p className="pm-meta">
            <span className="num">{exam.exam_date}</span>
            {exam.round_no ? <span>{exam.round_no}회차</span> : null}
            {exam.target_grade ? <span>고{exam.target_grade} 대상</span> : null}
          </p>

          <dl className="pm-stats">
            <div>
              <dt>응시</dt>
              <dd className="num">{stats.taker_count}명</dd>
            </div>
            <div>
              <dt>성적 행</dt>
              <dd className="num">{stats.score_count}</dd>
            </div>
            <div>
              <dt>평균</dt>
              <dd className="num">{score(stats.average)}</dd>
            </div>
            <div>
              <dt>표준편차</dt>
              <dd className="num">{score(stats.stddev)}</dd>
            </div>
            <div>
              <dt>최고점</dt>
              <dd className="num">{score(stats.highest_score)}</dd>
            </div>
            <div>
              <dt>상위 30% 컷</dt>
              <dd className="num">{score(stats.top30_score)}</dd>
            </div>
            <div>
              <dt>미대조 답안지</dt>
              <dd className="num">{stats.pending_sheet_count}장</dd>
            </div>
          </dl>

          {exam.notice && (
            <dl className="pm-defs">
              <dt>성적표 안내</dt>
              <dd>{exam.notice}</dd>
            </dl>
          )}
        </div>
      </Card>

      <AnswerKeyPanel examId={String(examId)} />

      <SheetUploadPanel
        examId={String(examId)}
        questionCount={questions.length}
        onUploaded={() => void detail.reload()}
      />

      <Card title="학생별 점수" aside="석차순" padding="none">
        <div className="pm-cardpad ui-stack ui-stack--md">
          <div className="ui-tabbar">
            <Tabs
              items={[
                { key: "제출", label: "제출", count: takenCount },
                { key: "미제출", label: "미제출", count: missingCount },
                { key: "전체", label: "전체", count: takenCount + missingCount },
              ]}
              value={tab}
              onChange={setTab}
              label="시험 제출 여부"
            />
          </div>
          <div className="pm-toolbar">
            <Field label="학생 찾기">
              {(props) => (
                <Input
                  {...props}
                  type="search"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="이름 또는 원번"
                />
              )}
            </Field>
          </div>
        </div>

        <Table<ExamStudentRow>
          rows={students}
          rowKey={(row) => row.student_id}
          dense
          caption="학생별 점수와 석차"
          empty={
            <EmptyState
              title={
                tab === "미제출"
                  ? "이 회차는 모든 학생이 시험을 제출했습니다"
                  : "조건에 맞는 학생이 없습니다"
              }
            />
          }
          columns={[
            {
              key: "rank",
              header: "석차",
              numeric: true,
              width: "4.5rem",
              sortValue: (row) => row.rank ?? 9999,
              cell: (row) => row.rank ?? "—",
            },
            {
              key: "name",
              header: "학생",
              sortValue: (row) => row.name,
              cell: (row) => row.name,
            },
            {
              // 원번은 이름이 섞인 값이라(2026-07-29 개정) 숫자 열이 아니다.
              key: "login_id",
              header: "원번",
              sortValue: (row) => row.login_id ?? "",
              cell: (row) => row.login_id ?? "—",
            },
            {
              key: "class",
              header: "반",
              cell: (row) => row.current_class ?? "미배정",
            },
            {
              key: "score",
              header: "점수",
              numeric: true,
              sortValue: (row) => row.total_score ?? -1,
              cell: (row) =>
                row.is_taken ? (
                  <>
                    {score(row.total_score)}
                    <span className="pm-none">
                      {" / "}
                      {score(row.max_score)}
                    </span>
                  </>
                ) : (
                  "—"
                ),
            },
            {
              key: "taken",
              header: "시험",
              width: "6.5rem",
              cell: (row) =>
                row.is_taken ? (
                  <Badge tone="success">제출</Badge>
                ) : (
                  <Badge tone="warning">시험 미제출</Badge>
                ),
            },
          ]}
        />
      </Card>

      <Card
        title="문항별 결과"
        aside={`${questions.length}문항`}
        padding="none"
      >
        <Table<ExamQuestionRow>
          rows={questions}
          rowKey={(row) => row.question_id}
          dense
          caption="문항별 정답률과 응답 분포"
          empty="아직 문항 정보가 등록되지 않았습니다"
          columns={[
            {
              key: "q",
              header: "번호",
              numeric: true,
              width: "4rem",
              sortValue: (row) => row.q_number,
              cell: (row) => row.q_number,
            },
            {
              key: "unit",
              header: "단원",
              sortValue: (row) => row.unit_major ?? "",
              cell: (row) => (
                <span className="pm-unit">
                  {row.unit_major ?? "미분류"}
                  {row.unit_minor && <small>{row.unit_minor}</small>}
                </span>
              ),
            },
            {
              key: "answer",
              header: "정답",
              numeric: true,
              width: "4rem",
              cell: (row) => row.answer ?? "—",
            },
            {
              key: "points",
              header: "배점",
              numeric: true,
              width: "4rem",
              cell: (row) => score(row.points),
            },
            {
              key: "rate",
              header: "정답률",
              numeric: true,
              width: "8rem",
              sortValue: (row) => row.correct_rate ?? -1,
              cell: (row) => {
                if (row.correct_rate === null) return "—";
                return (
                  <>
                    {row.correct_rate}%
                    {row.correct_rate < 40 && (
                      <>
                        {" "}
                        <Badge tone="danger">취약</Badge>
                      </>
                    )}
                  </>
                );
              },
            },
            {
              key: "correct",
              header: "정답",
              numeric: true,
              sortValue: (row) => row.correct_count,
              cell: (row) => row.correct_count,
            },
            {
              key: "wrong",
              header: "오답",
              numeric: true,
              sortValue: (row) => row.wrong_count,
              cell: (row) => row.wrong_count,
            },
            {
              key: "blank",
              header: "무응답",
              numeric: true,
              sortValue: (row) => row.blank_count,
              cell: (row) => row.blank_count,
            },
            {
              key: "multi",
              header: "복수마킹",
              numeric: true,
              sortValue: (row) => row.multi_count,
              cell: (row) =>
                row.multi_count > 0 ? <Badge tone="warning">{row.multi_count}</Badge> : 0,
            },
          ]}
        />
      </Card>
    </div>
  );
}

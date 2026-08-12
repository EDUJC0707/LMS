/**
 * /admin/exams/:examId/sheets — 스캔 보정.
 *
 * API  GET   /api/admin/exams/{exam_id}/sheets   → {kind, sheets[]} (손볼 장이 먼저)
 *      GET   /api/admin/sheets/{sheet_id}        → 정답 키 전량 + 그 장의 판독
 *      PATCH /api/admin/sheets/{sheet_id}        {student_id?, answers?, score?, confirm?}
 *      GET   /api/admin/sheets/{sheet_id}/scan   스캔 원본(인증 뒤에서만)
 *
 * 화면 설계
 * - 왼쪽이 지면, 오른쪽이 판독이다. 조교는 둘을 번갈아 보는 것이 일이라 한
 *   화면에 세워 두고 스크롤을 나눈다.
 * - 마킹 칸은 판독값이 들어간 채로 열린다. 고칠 것만 고치고 저장하면 그 문항만
 *   사람 것이 되고(재판독이 못 덮는다) 총점은 서버가 다시 낸다.
 * - 모의고사 장에는 문항이 없다. 고칠 것이 자기보고 점수 한 칸뿐이라 오른쪽이
 *   통째로 바뀐다.
 * - 주인을 못 고른 채 확정하면 그 점수는 **익명으로 평균에 든다**(decisions.md
 *   「익명 점수」). 되돌릴 수 있지만 버튼 이름이 그렇다고 말해 줘야 한다.
 * - 목록은 손볼 장부터 온다(서버 순서). 다음 장으로 넘어가는 것이 기본 동선이라
 *   저장하면 그 자리에 머무르지 않고 다음 장을 연다.
 */
import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";

import { http, useApi, useApiAction } from "../../../api";
import {
  Alert,
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  Field,
  Input,
  Loading,
} from "../../../components";
import { StudentPicker } from "./StudentPicker";
import type { DirectoryStudent } from "./directory";
import "./manage.css";
import type { ExamKind, SheetDetail, SheetQuestionRow, SheetRow } from "./types";

//: 채점 결과와 이상 사유는 축이 다르다 — 한 줄에 둘 다 있을 수는 없다.
const TONE: Record<string, "success" | "danger" | "warning" | "outline"> = {
  정답: "success",
  오답: "danger",
  판독불가: "danger",
  복수마킹: "warning",
  무응답: "outline",
};

export default function SheetReviewPage() {
  const { examId } = useParams();
  const list = useApi(
    () =>
      http
        .get<{ kind: ExamKind; sheets: SheetRow[] }>(`/admin/exams/${examId}/sheets`)
        .then((r) => r.data),
    [examId],
  );
  const sheets = useMemo(() => list.data?.sheets ?? [], [list.data]);
  const survey = list.data?.kind === "모의고사";

  const [index, setIndex] = useState(0);
  const current = sheets[index];

  const detail = useApi<SheetDetail | null>(
    async () => {
      if (!current) return null;
      const { data } = await http.get<SheetDetail>(`/admin/sheets/${current.sheet_id}`);
      return data;
    },
    [current?.sheet_id],
  );

  const [marks, setMarks] = useState<Record<number, string>>({});
  const [student, setStudent] = useState<DirectoryStudent | null>(null);
  const [score, setScore] = useState("");

  // 주인 없이 확정하면 그 점수는 **익명으로 평균에 든다.** 같은 버튼이 두 가지
  // 뜻을 갖게 되므로 이름을 가른다(문구를 덧붙이지 말고 이름을 고친다 — §8).
  const anonymous = survey && student === null;

  useEffect(() => {
    if (!detail.data) return;
    setMarks(
      Object.fromEntries(detail.data.questions.map((q) => [q.q_number, q.marked ?? ""])),
    );
    setStudent(detail.data.student);
    setScore(detail.data.recognized_score === null ? "" : String(detail.data.recognized_score));
  }, [detail.data]);

  const save = useApiAction(async (body: Record<string, unknown>) => {
    const { data } = await http.patch<SheetDetail>(`/admin/sheets/${current.sheet_id}`, body);
    return data;
  });

  const submit = async (confirm: boolean) => {
    const changed: Record<number, string> = {};
    for (const question of detail.data?.questions ?? []) {
      if (marks[question.q_number] !== (question.marked ?? "")) {
        changed[question.q_number] = marks[question.q_number];
      }
    }
    const body: Record<string, unknown> = {};
    if (student?.student_id !== detail.data?.student?.student_id) {
      body.student_id = student?.student_id ?? null;
    }
    if (Object.keys(changed).length > 0) body.answers = changed;
    const typed = score.trim() === "" ? null : Number(score);
    if (survey && typed !== (detail.data?.recognized_score ?? null)) body.score = typed;
    if (confirm) body.confirm = true;
    if (Object.keys(body).length === 0) return;
    const saved = await save.run(body);
    if (!saved) return;
    // 목록은 다시 부르지 않는다 — 저장한 장이 순서에서 뒤로 밀리면 지금 보고
    // 있는 자리가 다른 장으로 바뀐다. 순서는 연 시점 그대로 두고 행만 고친다.
    detail.setData(saved);
    list.setData({
      kind: list.data!.kind,
      sheets: sheets.map((row) => (row.sheet_id === saved.sheet_id ? saved : row)),
    });
  };

  if (list.loading) return <Loading label="스캔 목록을 불러오는 중…" />;
  if (list.error) return <ErrorState description={list.error} onRetry={list.reload} />;
  if (sheets.length === 0) return <EmptyState title="올라온 스캔이 없습니다" />;
  if (!current) return <EmptyState title="모든 장을 확인했습니다" />;

  return (
    <div className="ui-stack">
      <Card
        title={`${index + 1} / ${sheets.length}`}
        aside={
          <div className="pm-review__nav">
            <Badge tone={current.is_corrected ? "success" : "warning"}>
              {current.match_status}
            </Badge>
            {current.issue_count > 0 && (
              <Badge tone="danger">확인 {current.issue_count}</Badge>
            )}
            <Button
              size="sm"
              variant="ghost"
              disabled={index === 0}
              onClick={() => setIndex(index - 1)}
            >
              이전
            </Button>
            <Button
              size="sm"
              variant="ghost"
              disabled={index >= sheets.length - 1}
              onClick={() => setIndex(index + 1)}
            >
              다음
            </Button>
          </div>
        }
      >
        {save.error && (
          <Alert tone="danger" onClose={save.clearError}>
            {save.error}
          </Alert>
        )}
      </Card>

      <div className="pm-review">
        <div className="pm-review__scan">
          <img src={`/api/admin/sheets/${current.sheet_id}/scan`} alt={`스캔 ${index + 1}`} />
        </div>

        <div className="ui-stack ui-stack--md">
          <Card title="학생">
            <div className="ui-stack ui-stack--md">
              <dl className="pm-defs">
                <dt>인식된 이름</dt>
                <dd>{current.recognized_name ?? "—"}</dd>
                <dt>대조키</dt>
                <dd className="num">{current.recognized_matching_key ?? "—"}</dd>
              </dl>
              <StudentPicker value={student} onChange={setStudent} />
            </div>
          </Card>

          <Card
            title={survey ? "점수" : "문항"}
            aside={
              // 손글씨에서 읽은 점수는 결정적이지 않다 — 조교가 지면과 대조해야 한다.
              detail.data?.score_from_handwriting ? (
                <Badge tone="warning">손글씨</Badge>
              ) : detail.data?.total_score !== null ? (
                `${detail.data?.total_score}점`
              ) : undefined
            }
          >
            {detail.loading ? (
              <Loading label="판독을 불러오는 중…" />
            ) : (
              <div className="ui-stack ui-stack--md">
                {survey ? (
                  <Field label="자기보고 점수">
                    {(props) => (
                      <Input
                        {...props}
                        type="number"
                        min="0"
                        max="59"
                        value={score}
                        onChange={(e) => setScore(e.target.value)}
                      />
                    )}
                  </Field>
                ) : (
                  <ul className="pm-marks">
                    {(detail.data?.questions ?? []).map((question) => (
                      <MarkRow
                        key={question.q_number}
                        question={question}
                        value={marks[question.q_number] ?? ""}
                        onChange={(value) =>
                          setMarks((prev) => ({ ...prev, [question.q_number]: value }))
                        }
                      />
                    ))}
                  </ul>
                )}

                <div className="pm-actionblock pm-toolbar">
                  <div className="pm-toolbar__end">
                    <Button variant="ghost" loading={save.pending} onClick={() => submit(true)}>
                      {anonymous ? "익명으로 확정" : "확인"}
                    </Button>
                    <Button variant="primary" loading={save.pending} onClick={() => submit(false)}>
                      저장
                    </Button>
                  </div>
                </div>
              </div>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}

function MarkRow({
  question,
  value,
  onChange,
}: {
  question: SheetQuestionRow;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <li className="pm-marks__row">
      <span className="num pm-marks__no">{question.q_number}</span>
      <span className="num pm-marks__key">{question.answer}</span>
      <Input
        aria-label={`${question.q_number}번 마킹`}
        value={value}
        inputMode="numeric"
        maxLength={9}
        onChange={(e) => onChange(e.target.value)}
      />
      {question.result && <Badge tone={TONE[question.result] ?? "outline"}>{question.result}</Badge>}
      {question.issue_reason && (
        <Badge tone={TONE[question.issue_reason] ?? "warning"}>{question.issue_reason}</Badge>
      )}
      {question.is_corrected && <Badge tone="outline">보정</Badge>}
    </li>
  );
}

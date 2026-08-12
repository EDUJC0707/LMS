/**
 * 정답 키 입력 — /admin/exams/:examId 안.
 *
 * API  GET·PUT /api/admin/exams/{exam_id}/questions
 *      → {questions: [...], units: {대단원: [중단원, ...]}}
 *
 * 화면 설계
 * - 정답은 표를 한 칸씩 채우는 것보다 **붙여넣는 쪽이 빠르다**(`4 5 2 1 3` …).
 *   붙여넣으면 그 개수만큼 행이 서고, 배점·단원은 그 위에서 고친다.
 * - 단원 후보는 이미 쓴 값에서 온다(별도 표 없음). `datalist` 라 새 값은
 *   그냥 입력하면 되고, 다음 시험에서 후보로 뜬다.
 * - 대단원을 고르면 그 아래 중단원만 후보로 좁힌다.
 */
import { useEffect, useState } from "react";

import { http, useApi, useApiAction } from "../../../api";
import { Alert, Button, Card, Field, Input, Loading, Table, Textarea } from "../../../components";
import "./manage.css";
import type { QuestionKeyRow, QuestionKeyPayload } from "./types";

/** 붙여넣은 정답 → 행. 공백·쉼표·줄바꿈 아무거나 구분자로 받는다. */
export function parseAnswers(text: string): string[] {
  return text
    .split(/[\s,]+/)
    .map((token) => token.trim())
    .filter(Boolean);
}

export default function AnswerKeyPanel({ examId }: { examId: string }) {
  const key = useApi(
    () => http.get<QuestionKeyPayload>(`/admin/exams/${examId}/questions`).then((r) => r.data),
    [examId],
  );
  const [rows, setRows] = useState<QuestionKeyRow[]>([]);
  const [paste, setPaste] = useState("");

  useEffect(() => {
    if (key.data) setRows(key.data.questions);
  }, [key.data]);

  const save = useApiAction(async (questions: QuestionKeyRow[]) => {
    const { data } = await http.put<QuestionKeyPayload>(
      `/admin/exams/${examId}/questions`,
      { questions },
    );
    return data;
  });

  const units = key.data?.units ?? {};

  const applyPaste = () => {
    const answers = parseAnswers(paste);
    if (answers.length === 0) return;
    setRows(
      answers.map((answer, index) => ({
        q_number: index + 1,
        answer,
        points: rows[index]?.points ?? 1,
        unit_major: rows[index]?.unit_major ?? "",
        unit_minor: rows[index]?.unit_minor ?? "",
      })),
    );
    setPaste("");
  };

  const edit = (index: number, patch: Partial<QuestionKeyRow>) =>
    setRows((prev) => prev.map((row, i) => (i === index ? { ...row, ...patch } : row)));

  if (key.loading) return <Loading label="정답 키를 불러오는 중…" />;

  return (
    <Card
      title="정답 키"
      aside={rows.length > 0 ? `${rows.length}문항` : undefined}
    >
      <div className="ui-stack ui-stack--md">
        {save.error && <Alert tone="danger" onClose={save.clearError}>{save.error}</Alert>}

        <div className="pm-toolbar">
          <Field label="정답 붙여넣기">
            {(props) => (
              <Textarea
                {...props}
                rows={2}
                value={paste}
                onChange={(e) => setPaste(e.target.value)}
                placeholder="4 5 2 1 3 …"
              />
            )}
          </Field>
          <div className="pm-toolbar__end">
            <Button onClick={applyPaste} disabled={!paste.trim()}>
              행 만들기
            </Button>
          </div>
        </div>

        {rows.length > 0 && (
          <>
            <Table
              rows={rows}
              rowKey={(row) => row.q_number}
              columns={[
                { key: "q", header: "문항", cell: (row) => row.q_number },
                {
                  key: "answer",
                  header: "정답",
                  cell: (row, index) => (
                    <Input
                      value={row.answer}
                      onChange={(e) => edit(index, { answer: e.target.value })}
                      aria-label={`${row.q_number}번 정답`}
                    />
                  ),
                },
                {
                  key: "points",
                  header: "배점",
                  cell: (row, index) => (
                    <Input
                      type="number"
                      min="0"
                      step="0.5"
                      value={String(row.points ?? "")}
                      onChange={(e) => edit(index, { points: Number(e.target.value) })}
                      aria-label={`${row.q_number}번 배점`}
                    />
                  ),
                },
                {
                  key: "major",
                  header: "대단원",
                  cell: (row, index) => (
                    <Input
                      list="unit-majors"
                      value={row.unit_major ?? ""}
                      onChange={(e) => edit(index, { unit_major: e.target.value })}
                      aria-label={`${row.q_number}번 대단원`}
                    />
                  ),
                },
                {
                  key: "minor",
                  header: "중단원",
                  cell: (row, index) => (
                    <Input
                      list={`unit-minors-${index}`}
                      value={row.unit_minor ?? ""}
                      onChange={(e) => edit(index, { unit_minor: e.target.value })}
                      aria-label={`${row.q_number}번 중단원`}
                    />
                  ),
                },
              ]}
            />

            {/* 후보는 이미 쓴 값에서 온다 — 새 값은 그냥 입력하면 다음부터 뜬다. */}
            <datalist id="unit-majors">
              {Object.keys(units).map((major) => (
                <option key={major} value={major} />
              ))}
            </datalist>
            {rows.map((row, index) => (
              <datalist key={index} id={`unit-minors-${index}`}>
                {(units[row.unit_major ?? ""] ?? []).map((minor) => (
                  <option key={minor} value={minor} />
                ))}
              </datalist>
            ))}

            <div className="pm-toolbar">
              <div className="pm-toolbar__end">
                <Button
                  variant="primary"
                  loading={save.pending}
                  onClick={async () => {
                    const saved = await save.run(rows);
                    if (saved) {
                      setRows(saved.questions);
                      await key.reload();
                    }
                  }}
                >
                  저장
                </Button>
              </div>
            </div>
          </>
        )}
      </div>
    </Card>
  );
}

/**
 * 스캔 묶음 업로드 — /admin/exams/:examId 안.
 *
 * API  POST /api/admin/exams/{exam_id}/sheets  (multipart: pdf, question_count)
 *      → 202 {task_id} — 판독은 워커가 한다(27MB 업로드 + CPU 작업이라 웹
 *        프로세스를 붙잡아 두지 않는다). 진행은 아래 경로로 묻는다.
 *      GET /api/admin/omr-batches/{task_id} → {state, summary?}
 *
 * 화면 설계
 * - 문항 수는 카드가 아니라 시험이 정한다. 정답 키가 있으면 그 개수를 그대로
 *   쓴다 — 카드는 20줄이지만 16문항 회차가 있고, 안 쓴 줄을 넣으면 흐린 장에서
 *   인쇄 글리프가 답으로 승격된다.
 * - 결과는 판독·보류·대조를 한 줄로만 말한다. 무엇을 손봐야 하는지는 보정
 *   화면의 일이다.
 */
import { useEffect, useRef, useState } from "react";

import { http, useApiAction } from "../../../api";
import { Alert, Button, Card, Field, Input } from "../../../components";
import "./manage.css";
import type { ExamKind } from "./types";

/** 우리 카드 중 제일 큰 판형(답안25). 옛 카드는 20까지고, 서버가 판형별로 다시 본다. */
const MAX_QUESTIONS = 25;

interface UploadSummary {
  pages: number;
  read: number;
  held: number;
  matched: number;
  needs_review: number;
}

export default function SheetUploadPanel({
  examId,
  kind,
  questionCount,
  onUploaded,
}: {
  examId: string;
  kind: ExamKind;
  questionCount: number;
  onUploaded: () => void;
}) {
  // 모의고사 지면(성적 조사 카드)에는 문항이 없다 — 물을 것이 파일뿐이다.
  const survey = kind === "모의고사";
  const [file, setFile] = useState<File | null>(null);
  const [count, setCount] = useState(String(questionCount || ""));
  const [summary, setSummary] = useState<UploadSummary | null>(null);

  const [taskId, setTaskId] = useState<string | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const onUploadedRef = useRef(onUploaded);
  onUploadedRef.current = onUploaded;

  const upload = useApiAction(async () => {
    const form = new FormData();
    form.append("pdf", file as File);
    form.append("question_count", survey ? "0" : count);
    const { data } = await http.post<{ task_id: string }>(
      `/admin/exams/${examId}/sheets`,
      form,
      { headers: { "Content-Type": "multipart/form-data" } },
    );
    return data.task_id;
  });

  // 워커가 끝날 때까지 물어본다. 한 묶음이 65쪽에 2초 남짓이라 1초면 충분하다.
  useEffect(() => {
    if (!taskId) return;
    let alive = true;
    const timer = setInterval(async () => {
      const { data } = await http.get<{ state: string; summary?: UploadSummary; detail?: string }>(
        `/admin/omr-batches/${taskId}`,
      );
      if (!alive) return;
      if (data.summary) {
        setSummary(data.summary);
        setTaskId(null);
        onUploadedRef.current();
      } else if (data.detail) {
        setFailed(data.detail);
        setTaskId(null);
      }
    }, 1000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [taskId]);

  return (
    <Card title="스캔 올리기">
      <div className="ui-stack ui-stack--md">
        {(upload.error || failed) && (
          <Alert tone="danger" onClose={() => { upload.clearError(); setFailed(null); }}>
            {upload.error ?? failed}
          </Alert>
        )}

        <div className="pm-toolbar">
          <Field label="스캔 PDF">
            {(props) => (
              <Input
                {...props}
                type="file"
                accept="application/pdf,.pdf"
                onChange={(e) => {
                  setFile(e.target.files?.[0] ?? null);
                  setSummary(null);
                }}
              />
            )}
          </Field>
          {!survey && (
            <Field label="문항 수">
              {(props) => (
                <Input
                  {...props}
                  type="number"
                  min="1"
                  max={MAX_QUESTIONS}
                  value={count}
                  onChange={(e) => setCount(e.target.value)}
                />
              )}
            </Field>
          )}
          <div className="pm-toolbar__end">
            <Button
              variant="primary"
              loading={upload.pending || taskId !== null}
              disabled={!file || (!survey && !count)}
              onClick={async () => {
                setFailed(null);
                const id = await upload.run();
                if (!id) return;
                setTaskId(id);
                setFile(null);
              }}
            >
              {taskId ? "판독 중…" : "올리기"}
            </Button>
          </div>
        </div>

        {summary && (
          <p className="pm-meta">
            <span className="num">{summary.pages}장</span>
            <span>판독 {summary.read}</span>
            {summary.held > 0 && <span>보류 {summary.held}</span>}
            <span>대조됨 {summary.matched}</span>
            {summary.needs_review > 0 && <span>확인 필요 {summary.needs_review}</span>}
          </p>
        )}
      </div>
    </Card>
  );
}

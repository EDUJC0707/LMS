/**
 * 스캔 묶음 업로드 — /admin/exams/:examId 안.
 *
 * API  POST /api/admin/exams/{exam_id}/sheets  (multipart: pdf, question_count)
 *      → {pages, read, held, matched, needs_review}
 *
 * 화면 설계
 * - 문항 수는 카드가 아니라 시험이 정한다. 정답 키가 있으면 그 개수를 그대로
 *   쓴다 — 카드는 20줄이지만 16문항 회차가 있고, 안 쓴 줄을 넣으면 흐린 장에서
 *   인쇄 글리프가 답으로 승격된다.
 * - 결과는 판독·보류·대조를 한 줄로만 말한다. 무엇을 손봐야 하는지는 보정
 *   화면의 일이다.
 */
import { useState } from "react";

import { http, useApiAction } from "../../../api";
import { Alert, Button, Card, Field, Input } from "../../../components";
import "./manage.css";

interface UploadSummary {
  pages: number;
  read: number;
  held: number;
  matched: number;
  needs_review: number;
}

export default function SheetUploadPanel({
  examId,
  questionCount,
  onUploaded,
}: {
  examId: string;
  questionCount: number;
  onUploaded: () => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [count, setCount] = useState(String(questionCount || ""));
  const [summary, setSummary] = useState<UploadSummary | null>(null);

  const upload = useApiAction(async () => {
    const form = new FormData();
    form.append("pdf", file as File);
    form.append("question_count", count);
    const { data } = await http.post<UploadSummary>(`/admin/exams/${examId}/sheets`, form, {
      headers: { "Content-Type": "multipart/form-data" },
    });
    return data;
  });

  return (
    <Card title="스캔 올리기">
      <div className="ui-stack ui-stack--md">
        {upload.error && (
          <Alert tone="danger" onClose={upload.clearError}>
            {upload.error}
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
          <Field label="문항 수">
            {(props) => (
              <Input
                {...props}
                type="number"
                min="1"
                max="20"
                value={count}
                onChange={(e) => setCount(e.target.value)}
              />
            )}
          </Field>
          <div className="pm-toolbar__end">
            <Button
              variant="primary"
              loading={upload.pending}
              disabled={!file || !count}
              onClick={async () => {
                const result = await upload.run();
                if (!result) return;
                setSummary(result);
                setFile(null);
                onUploaded();
              }}
            >
              {upload.pending ? "판독 중…" : "올리기"}
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

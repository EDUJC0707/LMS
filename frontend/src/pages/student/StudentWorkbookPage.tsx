/**
 * 학생 워크북 열람 — GET /api/student/workbook (PRD 3.1.7)
 *
 * 서버는 매칭이 확정된 사진만 내려준다(대기·불일치는 아예 오지 않는다).
 * 사진이 본체이므로 크게 보여 주고, 탭하면 원본을 전체 크기로 연다.
 */
import { useState } from "react";

import { http, mediaUrl, useApi } from "../../api";
import {
  Badge,
  Card,
  EmptyState,
  ErrorState,
  Loading,
  Modal,
} from "../../components";
import { WorkbookPayload, WorkbookRow, dateTimeLabel, dayLabel } from "./lib";
import "./student.css";

function sessionLabel(row: WorkbookRow): string {
  if (!row.session) return "수업 회차 미지정";
  const no = row.session.session_no !== null ? ` · ${row.session.session_no}차시` : "";
  return `${dayLabel(row.session.session_date)}${no}`;
}

function assignmentLabel(done: boolean | null): string {
  if (done === null) return "과제 기록 없음";
  return done ? "과제 수행" : "과제 미수행";
}

export default function StudentWorkbookPage() {
  const [opened, setOpened] = useState<WorkbookRow | null>(null);
  const workbook = useApi(
    () => http.get<WorkbookPayload>("/student/workbook").then((r) => r.data),
    [],
  );

  if (workbook.loading) {
    return <Loading label="워크북 사진을 불러오는 중…" />;
  }

  if (workbook.error || !workbook.data) {
    return <ErrorState description={workbook.error ?? undefined} onRetry={workbook.reload} />;
  }

  const rows = workbook.data.workbooks;

  return (
    <>
      <Card
        title="회차별 사진"
        aside={rows.length > 0 ? `${rows.length}장` : undefined}
        padding={rows.length === 0 ? "none" : "md"}
      >
        {rows.length === 0 ? (
          <EmptyState title="아직 올라온 워크북 사진이 없습니다" />
        ) : (
          <ul className="st-shots">
            {rows.map((row) => (
              <li key={row.submission_id}>
                <button type="button" className="st-shot" onClick={() => setOpened(row)}>
                  <img
                    className="st-shot__img"
                    src={mediaUrl(row.image_url)}
                    alt={`${sessionLabel(row)} 워크북 사진`}
                    loading="lazy"
                  />
                  <span className="st-shot__body">
                    <span className="st-shot__date">{sessionLabel(row)}</span>
                    <span className="ui-row">
                      {row.performance_grade && (
                        <Badge tone="accent">수행도 {row.performance_grade}</Badge>
                      )}
                      <Badge
                        tone={
                          row.assignment_done === null
                            ? "neutral"
                            : row.assignment_done
                              ? "success"
                              : "warning"
                        }
                      >
                        {assignmentLabel(row.assignment_done)}
                      </Badge>
                    </span>
                    <span className="st-shot__meta">
                      {dateTimeLabel(row.uploaded_at)} 업로드
                    </span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Modal
        open={opened !== null}
        onClose={() => setOpened(null)}
        wide
        title={opened ? sessionLabel(opened) : "워크북 사진"}
      >
        {opened && (
          <>
            <img
              className="st-shot__full"
              src={mediaUrl(opened.image_url)}
              alt={`${sessionLabel(opened)} 워크북 사진 원본`}
            />
            <div className="ui-row" style={{ marginTop: "var(--space-md)" }}>
              {opened.performance_grade && (
                <Badge tone="accent">수행도 {opened.performance_grade}</Badge>
              )}
              <Badge
                tone={
                  opened.assignment_done === null
                    ? "neutral"
                    : opened.assignment_done
                      ? "success"
                      : "warning"
                }
              >
                {assignmentLabel(opened.assignment_done)}
              </Badge>
              <span className="st-shot__meta">{dateTimeLabel(opened.uploaded_at)} 업로드</span>
            </div>
          </>
        )}
      </Modal>
    </>
  );
}

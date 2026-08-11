/**
 * 자녀 워크북 사진 — GET /api/parent/workbook?student_id=
 *
 * 직원이 자녀 것으로 확정한 사진만 내려온다(매칭 대기·불일치는 서버가
 * 아예 주지 않는다 — PRD 3.1.7). 없는 사진을 지어내지 않는다.
 */
import { http, mediaUrl, useApi } from "../../api";
import { Badge, Card, EmptyState, ErrorState, Loading, ScopeBar } from "../../components";
import { NO_CHILD_TITLE, useChild } from "./childContext";
import { PreEnrollNotice } from "./PreEnrollNotice";
import { dateTimeLabel, dayLabel } from "./format";
import "./parent.css";
import { WorkbookList } from "./types";

export default function ParentWorkbookPage() {
  const { studentId, child, picker, enrolled } = useChild();

  const workbook = useApi<WorkbookList | null>(
    () =>
      studentId === null || !enrolled
        ? Promise.resolve(null)
        : http
            .get<WorkbookList>("/parent/workbook", { params: { student_id: studentId } })
            .then((response) => response.data),
    [studentId, enrolled],
  );

  const rows = workbook.data?.workbooks ?? [];

  return (
    <>
      {picker && <ScopeBar>{picker}</ScopeBar>}

      {studentId === null ? (
        <Card padding="none">
          <EmptyState title={NO_CHILD_TITLE} />
        </Card>
      ) : !enrolled ? (
        <PreEnrollNotice child={child} what="워크북 열람" />
      ) : workbook.loading ? (
        <Loading label="워크북 사진을 불러오는 중…" />
      ) : workbook.error ? (
        <ErrorState description={workbook.error} onRetry={workbook.reload} />
      ) : (
        // 상단바가 이미 "워크북"이다 — 카드는 그 안이 무엇인지(수업별 사진)만 말한다.
        <Card
          title="수업별 사진"
          aside={rows.length > 0 ? `${rows.length}장` : undefined}
          padding={rows.length === 0 ? "none" : "md"}
        >
          {rows.length === 0 ? (
            <EmptyState title="아직 올라온 워크북 사진이 없습니다" />
          ) : (
            <div className="parent-photos">
              {rows.map((row) => (
                <figure key={row.submission_id} className="parent-photo">
                  <a
                    className="parent-photo__link"
                    href={mediaUrl(row.image_url)}
                    target="_blank"
                    rel="noreferrer"
                  >
                    <img
                      className="parent-photo__img"
                      src={mediaUrl(row.image_url)}
                      alt={`${
                        row.session ? dayLabel(row.session.session_date) : "수업일 미확인"
                      } 워크북 사진${child?.name ? ` · ${child.name}` : ""}`}
                      loading="lazy"
                    />
                  </a>
                  <figcaption className="parent-photo__cap">
                    <span className="parent-photo__date">
                      {row.session ? dayLabel(row.session.session_date) : "수업일 미확인"}
                      {row.session?.session_no ? ` · ${row.session.session_no}차시` : ""}
                    </span>
                    <span className="parent-photo__meta">
                      {row.performance_grade && (
                        <Badge tone="neutral">수행도 {row.performance_grade}</Badge>
                      )}
                      {row.assignment_done === true && <Badge tone="success">과제 완료</Badge>}
                      {row.assignment_done === false && <Badge tone="warning">과제 미완</Badge>}
                      <span>{dateTimeLabel(row.uploaded_at)} 올림</span>
                    </span>
                  </figcaption>
                </figure>
              ))}
            </div>
          )}
        </Card>
      )}
    </>
  );
}

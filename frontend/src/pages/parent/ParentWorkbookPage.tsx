/**
 * 자녀 워크북 사진 — GET /api/parent/workbook?student_id=
 *
 * 학원에서 자녀 것으로 확정한 사진만 내려온다(매칭 대기·불일치는 서버가
 * 아예 주지 않는다 — PRD 3.1.7). 없는 사진을 지어내지 않는다.
 */
import { http, mediaUrl, useApi } from "../../api";
import { Badge, Card, EmptyState, ErrorState, Loading, PageHeader } from "../../components";
import { NO_CHILD_DESC, NO_CHILD_TITLE, useChild } from "./childContext";
import { dateTimeLabel, dayLabel } from "./format";
import "./parent.css";
import { WorkbookList } from "./types";

export default function ParentWorkbookPage() {
  const { studentId, child, picker } = useChild();

  const workbook = useApi<WorkbookList | null>(
    () =>
      studentId === null
        ? Promise.resolve(null)
        : http
            .get<WorkbookList>("/parent/workbook", { params: { student_id: studentId } })
            .then((response) => response.data),
    [studentId],
  );

  const rows = workbook.data?.workbooks ?? [];

  return (
    <>
      <PageHeader
        title="워크북"
        description="수업 시간에 학원이 찍어 올린 자녀의 워크북 사진입니다. 사진을 누르면 크게 볼 수 있습니다."
        actions={picker}
      />

      {studentId === null ? (
        <Card>
          <EmptyState title={NO_CHILD_TITLE} description={NO_CHILD_DESC} />
        </Card>
      ) : workbook.loading ? (
        <Loading />
      ) : workbook.error ? (
        <ErrorState description={workbook.error} onRetry={workbook.reload} />
      ) : (
        <Card
          title="수업별 워크북"
          aside={rows.length > 0 ? `${rows.length}장` : undefined}
        >
          {rows.length === 0 ? (
            <EmptyState
              title="아직 올라온 워크북 사진이 없습니다"
              description="수업에서 찍은 사진은 학원이 자녀 것으로 확인한 뒤에 이 화면에 올라옵니다."
            />
          ) : (
            <>
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
              <p className="parent-note parent-note--spaced">
                수행도와 과제 여부는 수업을 진행한 선생님이 남긴 기록입니다.
              </p>
            </>
          )}
        </Card>
      )}
    </>
  );
}

/** 워크북 사진 공용 뷰 — 확정(자동/수동 매칭)분만 노출된다(PRD 3.1.7). */
/* eslint-disable @typescript-eslint/no-explicit-any */
import { mediaUrl } from "../api";

export default function WorkbookView({ data }: { data: any }) {
  const rows = data.workbooks as any[];
  return (
    <div>
      {rows.length === 0 ? (
        <p className="muted">확정된 워크북 사진 없음(매핑 대기·불일치는 노출되지 않음)</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>사진</th>
              <th>수업 회차</th>
              <th>수행도</th>
              <th>과제 수행</th>
              <th>업로드 시각</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.submission_id}>
                <td>
                  <a href={mediaUrl(row.image_url)} target="_blank" rel="noreferrer">
                    <img className="thumb" src={mediaUrl(row.image_url)} alt="워크북 사진" />
                  </a>
                </td>
                <td>
                  {row.session
                    ? `${row.session.session_date} (${row.session.session_no ?? "-"}차시)`
                    : "-"}
                </td>
                <td>{row.performance_grade ?? "-"}</td>
                <td>
                  {row.assignment_done === null || row.assignment_done === undefined
                    ? "기록 없음"
                    : row.assignment_done
                      ? "수행"
                      : "미수행"}
                </td>
                <td>{row.uploaded_at}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

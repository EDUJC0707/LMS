/** 동보 신청 관리 — 목록(상태 필터)·승인(지급 체인)·거절. */
/* eslint-disable @typescript-eslint/no-explicit-any */
import { useState } from "react";

import { api, errMsg } from "../../api";
import { Msg, useLoad } from "../../ui";

export default function MakeupAdminPage() {
  const [status, setStatus] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);

  const list = useLoad<any>(
    async () =>
      (await api.get("/admin/makeup-requests", { params: status ? { status } : {} })).data,
    [status],
  );

  const act = async (fn: () => Promise<any>, describe: (data: any) => string) => {
    setError(null);
    setOk(null);
    try {
      const { data } = await fn();
      setOk(describe(data));
      await list.reload();
    } catch (e) {
      setError(errMsg(e));
    }
  };

  return (
    <section>
      <h2>동보 신청 관리</h2>
      <p className="inline">
        상태 필터:{" "}
        <select value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">전체</option>
          {["신청", "승인", "지급완료", "거절"].map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </select>
      </p>
      <Msg error={list.error ?? error} ok={ok} />
      {list.data && (
        <table>
          <thead>
            <tr>
              <th>번호</th>
              <th>학생</th>
              <th>결석 회차</th>
              <th>attendance_id</th>
              <th>경로</th>
              <th>신청 주체</th>
              <th>상태</th>
              <th>처리</th>
            </tr>
          </thead>
          <tbody>
            {list.data.requests.length === 0 && (
              <tr>
                <td colSpan={8} className="muted">
                  신청 없음
                </td>
              </tr>
            )}
            {list.data.requests.map((row: any) => (
              <tr key={row.makeup_id}>
                <td>{row.makeup_id}</td>
                <td>
                  {row.student.name} (원번 {row.student.unique_id})
                </td>
                <td>
                  {row.session_date} — {row.course_name} {row.week_no}주차
                </td>
                <td>{row.attendance_id}</td>
                <td>{row.source}</td>
                <td>{row.requested_by ?? "-"}</td>
                <td>
                  {row.status}
                  {row.granted_at && <span className="muted"> ({row.granted_at})</span>}
                </td>
                <td className="inline">
                  <button
                    onClick={() =>
                      act(
                        () => api.post(`/admin/makeup-requests/${row.makeup_id}/approve`),
                        (data) =>
                          `승인 완료 — 영상권한 #${data.video_grant.grant_id} 지급(만료 ${data.video_grant.expires_at})`,
                      )
                    }
                  >
                    승인(지급)
                  </button>
                  <button
                    onClick={() =>
                      act(
                        () => api.post(`/admin/makeup-requests/${row.makeup_id}/reject`),
                        () => "거절 처리 완료",
                      )
                    }
                  >
                    거절
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="muted">
        이미 처리된 신청을 다시 승인/거절하면 400 사유가 표시된다. 출결이 정정돼 결석이
        아니게 된 신청도 400.
      </p>
    </section>
  );
}

/** 내 알림 내역 — 대상 3분기(학생/학부모/직원) 매칭 + 페이지네이션. */
import { useState } from "react";

import { api } from "../api";
import { Msg, useLoad } from "../ui";

interface NotificationRow {
  notif_id: number;
  type: string;
  channel: string;
  title: string | null;
  body: string | null;
  status: string;
  ref_type: string | null;
  ref_id: number | null;
  sent_at: string | null;
  created_at: string;
}
interface Page {
  count: number;
  next: string | null;
  previous: string | null;
  results: NotificationRow[];
}

export default function NotificationsPage() {
  const [page, setPage] = useState(1);
  const { data, error, loading } = useLoad<Page>(
    async () => (await api.get("/me/notifications", { params: { page } })).data,
    [page],
  );
  return (
    <section>
      <h2>알림 내역</h2>
      <Msg error={error} />
      {loading && <p>불러오는 중…</p>}
      {data && (
        <>
          <p className="muted">총 {data.count}건</p>
          <table>
            <thead>
              <tr>
                <th>유형</th>
                <th>채널</th>
                <th>제목</th>
                <th>본문</th>
                <th>상태</th>
                <th>원인</th>
                <th>발송 시각</th>
              </tr>
            </thead>
            <tbody>
              {data.results.map((row) => (
                <tr key={row.notif_id}>
                  <td>{row.type}</td>
                  <td>{row.channel}</td>
                  <td>{row.title}</td>
                  <td>{row.body}</td>
                  <td>{row.status}</td>
                  <td>{row.ref_type ? `${row.ref_type}#${row.ref_id}` : "-"}</td>
                  <td>{row.sent_at ?? "(발송 대기)"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="inline">
            <button disabled={!data.previous} onClick={() => setPage(page - 1)}>
              이전
            </button>
            <span> {page}쪽 </span>
            <button disabled={!data.next} onClick={() => setPage(page + 1)}>
              다음
            </button>
          </p>
        </>
      )}
    </section>
  );
}

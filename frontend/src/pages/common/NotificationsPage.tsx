/**
 * 알림 내역 — /notifications.
 *
 * API: GET /api/me/notifications?page=  (최신순·20건. 읽음 처리 API 는 없다)
 *
 * 화면 규칙
 * - 날짜 묶음으로 끊어 읽는다(오늘·어제·7월 22일).
 * - 유형은 서버 값(성적·영상권한·클리닉대상 …)을 그대로 보여 준다. 값집합이
 *   열려 있어(백엔드 Notification.Type 주석) 화면에서 임의로 묶지 않는다.
 * - 발송 실패는 숨기지 않는다 — 알림톡이 안 갔더라도 내용은 여기서 볼 수 있다.
 */
import { useState } from "react";
import { Link } from "react-router-dom";

import { http, useApi } from "../../api";
import { useMe } from "../../auth";
import {
  Badge,
  Card,
  EmptyState,
  ErrorState,
  Loading,
  PageHeader,
  Pagination,
} from "../../components";
import { API_PAGE_SIZE, Paged, formatDay, formatTime, groupByDay } from "./boards";
import "./common.css";

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

export default function NotificationsPage() {
  const { me } = useMe();
  const [page, setPage] = useState(1);

  const list = useApi(
    () =>
      http
        .get<Paged<NotificationRow>>("/me/notifications", { params: { page } })
        .then((response) => response.data),
    [page],
  );

  const rows = list.data?.results ?? [];
  const totalPages = Math.max(1, Math.ceil((list.data?.count ?? 0) / API_PAGE_SIZE));
  const groups = groupByDay(rows, (row) => row.created_at);

  // 성적 알림에서 성적표로 바로 가는 길. 자녀를 고르는 학부모 화면은 어느
  // 자녀인지 알 수 없으므로 만들지 않는다(서버가 안 준 것을 짐작하지 않는다).
  const gradeLinkable = me?.role === "학생" && me.student?.enrollment_status === "등록";

  return (
    <>
      <PageHeader title="알림" />

      {list.loading ? (
        <Loading label="알림을 불러오는 중…" />
      ) : list.error ? (
        <ErrorState description={list.error} onRetry={list.reload} />
      ) : rows.length === 0 ? (
        <Card>
          <EmptyState title="아직 받은 알림이 없습니다" />
        </Card>
      ) : (
        <div className="ui-stack">
          <Card padding="none" className="cm-clip">
            {groups.map((group) => (
              <section className="cm-daygroup" key={group.key}>
                <h2 className="cm-daygroup__label">{group.label}</h2>
                <ul className="cm-notif">
                  {group.rows.map((row) => (
                    <li key={row.notif_id}>
                      <NotificationItem row={row} gradeLinkable={gradeLinkable} />
                    </li>
                  ))}
                </ul>
              </section>
            ))}
          </Card>

          <Pagination
            page={page}
            totalPages={totalPages}
            onChange={setPage}
            status={`전체 ${list.data?.count ?? 0}건`}
          />
        </div>
      )}
    </>
  );
}

function NotificationItem({
  row,
  gradeLinkable,
}: {
  row: NotificationRow;
  gradeLinkable: boolean;
}) {
  const failed = row.status === "실패";
  const waiting = row.status === "대기";
  const when = row.sent_at ? formatTime(row.sent_at) : formatDay(row.created_at);
  const showGradeLink = gradeLinkable && row.ref_type === "exam" && row.ref_id !== null;

  return (
    <article className="cm-notif__item">
      <div className="cm-notif__head">
        <Badge tone="neutral">{row.type}</Badge>
        <h3 className="cm-notif__title">{row.title ?? `${row.type} 안내`}</h3>
        {failed && <Badge tone="danger">발송 실패</Badge>}
      </div>

      <span className="cm-notif__when">
        {waiting ? "보내기 전" : when}
        <br />
        {row.channel}
      </span>

      {row.body && <p className="cm-notif__body">{row.body}</p>}

      {failed && (
        <p className="cm-notif__body">알림톡 발송 실패</p>
      )}

      {showGradeLink && (
        <p className="cm-notif__link">
          <Link to={`/student/grades/${row.ref_id}`}>성적표 보기</Link>
        </p>
      )}
    </article>
  );
}

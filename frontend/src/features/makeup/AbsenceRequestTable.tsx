/**
 * 결석 목록 + 신청 버튼 — 학생·학부모 동보 화면이 함께 쓰는 표.
 *
 * 두 화면이 같은 서버 필드(attendance_id·makeup_status)를 받으므로 판정(absences.ts)과
 * 표현을 한 곳에 둔다. 화면마다 다른 것은 날짜 서식과 빈 상태 문구뿐이라 그것만 받는다.
 *
 * 규칙
 * - 신청할 수 있는 결석이 하나도 없으면 "신청" 열을 아예 만들지 않는다
 *   (누를 수 없는 버튼을 회색으로 남겨 두지 않는다 — PRD §4 상태 기반 노출).
 * - 이미 신청·승인·지급된 결석은 상태만 보여 준다. 거절은 다시 신청할 수 있다.
 * - 결석이 0건일 때의 빈 상태는 호출측이 그린다(표 머리글만 남는 화면을 만들지 않는다).
 */
import { Badge, Button, StatusBadge, Table } from "../../components";
import { MakeupAbsence, isRequestable, requestableCount } from "./absences";

export interface AbsenceRequestTableProps {
  rows: MakeupAbsence[];
  /** "2026-07-15" → "7월 15일(수)" — 화면별 서식 함수를 그대로 받는다. */
  formatDate: (iso: string) => string;
  onRequest: (row: MakeupAbsence) => void;
  /** 지금 신청 중인 결석의 attendance_id. 없으면 null. */
  pendingId: number | null;
  caption: string;
}

export function AbsenceRequestTable({
  rows,
  formatDate,
  onRequest,
  pendingId,
  caption,
}: AbsenceRequestTableProps) {
  const openCount = requestableCount(rows);

  return (
    <Table<MakeupAbsence>
      rows={rows}
      rowKey={(row) => row.attendance_id}
      caption={caption}
      columns={[
        {
          key: "date",
          header: "결석한 날",
          cell: (row) => formatDate(row.date),
          sortValue: (row) => row.date,
        },
        {
          key: "status",
          header: "보강 영상",
          width: "9rem",
          cell: (row) =>
            row.makeup_status ? (
              <StatusBadge status={row.makeup_status} />
            ) : (
              <Badge tone="outline">신청 전</Badge>
            ),
        },
        ...(openCount > 0
          ? [
              {
                key: "action",
                header: "신청",
                width: "9rem",
                align: "right" as const,
                cell: (row: MakeupAbsence) =>
                  isRequestable(row) ? (
                    <Button
                      size="sm"
                      variant="primary"
                      loading={pendingId === row.attendance_id}
                      onClick={() => onRequest(row)}
                    >
                      {row.makeup_status === "거절" ? "다시 신청" : "신청하기"}
                    </Button>
                  ) : null,
              },
            ]
          : []),
      ]}
    />
  );
}

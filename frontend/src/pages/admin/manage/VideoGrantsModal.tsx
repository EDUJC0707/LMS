/**
 * 영상 하나의 지급 내역 — 개별 회수 (FLOW §5)
 *
 *   GET  /api/admin/videos/grants?video_id=
 *   POST /api/admin/videos/grants/{id}/revoke
 *
 * **손으로 하는 것은 회수뿐이다.** 지급은 `출결 확정` 이 묶음으로 하고
 * 수동 지급은 만들지 않기로 했다 — 그래서 이 표의 유일한 버튼이 회수다.
 * 회수된 줄도 남는다(지급·회수는 이력이다).
 */
import { http, useApi, useApiAction } from "../../../api";
import {
  Button,
  EmptyState,
  ErrorState,
  Loading,
  Modal,
  Table,
} from "../../../components";

interface GrantRow {
  grant_id: number;
  student: { student_id: number; name: string; matching_key: string };
  video_title: string;
  source: string;
  granted_at: string | null;
  expires_at: string | null;
  revoked_at: string | null;
}

function day(value: string | null): string {
  return value ? value.slice(0, 10) : "—";
}

export function VideoGrantsModal({
  videoId,
  title,
  onClose,
}: {
  videoId: number;
  title: string;
  onClose: () => void;
}) {
  const list = useApi(
    async () =>
      (await http.get<{ grants: GrantRow[] }>(`/admin/videos/grants?video_id=${videoId}`))
        .data.grants,
    [videoId],
  );
  // 값은 인자로 넘긴다 — 이 훅은 첫 렌더의 클로저를 붙든다(api/useApi.ts).
  const revoke = useApiAction(async (grantId: number) => {
    await http.post(`/admin/videos/grants/${grantId}/revoke`);
    await list.reload();
    return true;
  });

  const rows = list.data ?? [];

  return (
    <Modal open onClose={onClose} title={title} wide footer={<Button onClick={onClose}>닫기</Button>}>
      {list.initialLoading ? (
        <Loading label="지급 내역을 불러오는 중…" />
      ) : list.error ? (
        <ErrorState description={list.error} onRetry={list.reload} />
      ) : (
        <>
          {revoke.error && (
            <ErrorState description={revoke.error} onRetry={revoke.clearError} />
          )}
          <Table<GrantRow>
            rows={rows}
            rowKey={(row) => row.grant_id}
            caption="영상 지급 내역"
            dense
            empty={<EmptyState title="지급된 권한이 없습니다" />}
            columns={[
              { key: "student", header: "학생", cell: (row) => row.student.name },
              {
                key: "key",
                header: "대조키",
                cell: (row) => <span className="num">{row.student.matching_key}</span>,
              },
              { key: "source", header: "경로", cell: (row) => row.source },
              { key: "granted", header: "지급", cell: (row) => day(row.granted_at) },
              { key: "expires", header: "만료", cell: (row) => day(row.expires_at) },
              {
                key: "actions",
                header: "",
                align: "right",
                width: "6rem",
                cell: (row) =>
                  row.revoked_at ? (
                    <span className="pm-none">회수 {day(row.revoked_at)}</span>
                  ) : (
                    <Button
                      size="sm"
                      variant="danger"
                      loading={revoke.pending}
                      onClick={() => void revoke.run(row.grant_id)}
                    >
                      회수
                    </Button>
                  ),
              },
            ]}
          />
        </>
      )}
    </Modal>
  );
}

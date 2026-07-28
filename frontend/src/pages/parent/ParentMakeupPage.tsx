/**
 * 보강 영상(동보) 신청 — 자녀 결석 목록 + POST /api/parent/makeup-request
 *
 * 결석 목록은 GET /api/parent/home?month= 의 absences 블록에서 온다.
 * ⚠ 현재 백엔드는 absences 에 attendance_id 를 내려주지 않는데(신청 API 는 그
 *   id 를 요구한다), 그래서 신청 버튼은 id 가 실제로 내려온 결석에만 그린다 —
 *   없는 자격을 회색 버튼으로 만들어 두지 않는다(PRD §4 상태 기반 노출).
 *   서버가 id 를 실어 주는 순간 이 화면은 고칠 것 없이 신청까지 동작한다.
 */
import { useState } from "react";

import { http, useApi, useApiAction } from "../../api";
import {
  Alert,
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  Loading,
  PageHeader,
  StatusBadge,
  Table,
} from "../../components";
import { NO_CHILD_DESC, NO_CHILD_TITLE, useChild } from "./childContext";
import { currentMonth, dayLabel, monthLabel, shiftMonth } from "./format";
import "./parent.css";
import { AbsenceRow, MakeupBlock, ParentHome } from "./types";

export default function ParentMakeupPage() {
  const { studentId, child, picker } = useChild();
  const [month, setMonth] = useState(currentMonth());
  const [requesting, setRequesting] = useState<number | null>(null);

  const home = useApi<ParentHome | null>(
    () =>
      studentId === null
        ? Promise.resolve(null)
        : http
            .get<ParentHome>("/parent/home", { params: { student_id: studentId, month } })
            .then((response) => response.data),
    [studentId, month],
  );

  const request = useApiAction(async (attendanceId: number) => {
    const { data } = await http.post<{ makeup: MakeupBlock }>("/parent/makeup-request", {
      attendance_id: attendanceId,
    });
    return data.makeup;
  });

  const submit = async (row: AbsenceRow) => {
    if (row.attendance_id === undefined) return;
    setRequesting(row.attendance_id);
    const created = await request.run(row.attendance_id);
    setRequesting(null);
    // 신청 결과는 표의 상태 뱃지로 바로 보인다 — 토스트는 띄우지 않는다.
    if (created) await home.reload();
  };

  const absences = home.data?.absences;
  const started = home.data?.calendar != null;
  // 신청할 수 있는 결석이 하나도 없으면 신청 열 자체를 만들지 않는다.
  const requestable = (absences ?? []).some(
    (row) => row.makeup_status === null && row.attendance_id !== undefined,
  );
  const blocked = (absences ?? []).some(
    (row) => row.makeup_status === null && row.attendance_id === undefined,
  );

  return (
    <>
      <PageHeader
        title="동보 신청"
        description={`동보는 결석한 수업의 보강 영상입니다. ${
          child?.name ? `${child.name} 학생이 ` : "자녀가 "
        }결석한 수업의 영상을 신청하고 처리 상태를 확인합니다.`}
        actions={picker}
      />

      {studentId === null ? (
        <Card>
          <EmptyState title={NO_CHILD_TITLE} description={NO_CHILD_DESC} />
        </Card>
      ) : home.loading ? (
        <Loading />
      ) : home.error ? (
        <ErrorState description={home.error} onRetry={home.reload} />
      ) : (
        <div className="ui-stack">
          {request.error && (
            <Alert tone="danger" onClose={request.clearError}>
              {request.error}
            </Alert>
          )}

          <Card
            title="결석한 수업"
            actions={
              <div className="parent-monthnav">
                <Button size="sm" onClick={() => setMonth(shiftMonth(month, -1))}>
                  이전 달
                </Button>
                <span className="parent-monthnav__label">{monthLabel(month)}</span>
                <Button size="sm" onClick={() => setMonth(shiftMonth(month, 1))}>
                  다음 달
                </Button>
              </div>
            }
            padding={absences && absences.length > 0 ? "none" : "md"}
          >
            {!started ? (
              <EmptyState
                title="아직 수업이 시작되지 않았습니다"
                description="등록이 확정되고 수업이 시작되면 결석 기록과 보강 영상 신청이 여기에 열립니다."
              />
            ) : !absences || absences.length === 0 ? (
              <EmptyState
                title={`${monthLabel(month)}에는 결석이 없습니다`}
                description="다른 달을 보려면 위의 달 이동 단추를 눌러 주세요."
              />
            ) : (
              <Table
                rows={absences}
                rowKey={(row) => row.date}
                caption="결석일과 보강 영상 신청 상태"
                columns={[
                  {
                    key: "date",
                    header: "결석한 날",
                    cell: (row: AbsenceRow) => dayLabel(row.date),
                  },
                  {
                    key: "status",
                    header: "보강 영상",
                    width: "9rem",
                    cell: (row: AbsenceRow) =>
                      row.makeup_status ? (
                        <StatusBadge status={row.makeup_status} />
                      ) : (
                        <Badge tone="outline">신청 전</Badge>
                      ),
                  },
                  ...(requestable
                    ? [
                        {
                          key: "action",
                          header: "신청",
                          width: "8rem",
                          align: "right" as const,
                          cell: (row: AbsenceRow) =>
                            row.makeup_status === null && row.attendance_id !== undefined ? (
                              <Button
                                size="sm"
                                variant="primary"
                                loading={requesting === row.attendance_id}
                                onClick={() => submit(row)}
                              >
                                신청하기
                              </Button>
                            ) : null,
                        },
                      ]
                    : []),
                ]}
              />
            )}
          </Card>

          <Card title="신청하면 이렇게 진행됩니다">
            <ol className="parent-steps">
              <li>
                <strong>신청</strong> — 학부모나 학생이 결석한 수업의 보강 영상을 요청합니다.
              </li>
              <li>
                <strong>승인</strong> — 학원이 결석 사유와 수업 회차를 확인합니다.
              </li>
              <li>
                <strong>지급완료</strong> — 영상이 열리고, 시청 기한이 자녀 홈의 &lsquo;곧 마감되는
                것&rsquo;에 나타납니다.
              </li>
            </ol>
            {blocked && (
              <p className="parent-note parent-note--spaced">
                신청 단추가 보이지 않는 결석은 이 화면에서 바로 신청할 수 없습니다. 학원으로 연락해
                주시면 보강 영상을 열어 드립니다.
              </p>
            )}
          </Card>
        </div>
      )}
    </>
  );
}

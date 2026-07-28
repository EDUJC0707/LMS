/**
 * 보강 영상(동보) 신청 — 자녀 결석 목록 + POST /api/parent/makeup-request
 *
 * 결석 목록은 GET /api/parent/home?month= 의 absences 블록에서 온다. 서버가
 * 결석마다 attendance_id 를 함께 내려주므로(2026-07-28 보강) 표의 버튼 한 번으로
 * 신청이 끝난다 — "신청 단추가 보이지 않는 결석" 안내는 더 이상 필요 없다.
 *
 * 신청 대상 판정·표는 features/makeup 에서 학생 화면과 공유한다.
 */
import { useState } from "react";

import { http, useApi, useApiAction } from "../../api";
import {
  Alert,
  Button,
  Card,
  EmptyState,
  ErrorState,
  Loading,
  PageHeader,
} from "../../components";
import { AbsenceRequestTable } from "../../features/makeup/AbsenceRequestTable";
import { MakeupAbsence, requestableCount } from "../../features/makeup/absences";
import { NO_CHILD_DESC, NO_CHILD_TITLE, useChild } from "./childContext";
import { currentMonth, dayLabel, monthLabel, shiftMonth } from "./format";
import { PreEnrollNotice } from "./PreEnrollNotice";
import "./parent.css";
import { MakeupBlock, ParentHome } from "./types";

export default function ParentMakeupPage() {
  const { studentId, child, picker, enrolled } = useChild();
  const [month, setMonth] = useState(currentMonth());
  const [requesting, setRequesting] = useState<number | null>(null);

  const home = useApi<ParentHome | null>(
    () =>
      studentId === null || !enrolled
        ? Promise.resolve(null)
        : http
            .get<ParentHome>("/parent/home", { params: { student_id: studentId, month } })
            .then((response) => response.data),
    [studentId, enrolled, month],
  );

  const request = useApiAction(async (attendanceId: number) => {
    const { data } = await http.post<{ makeup: MakeupBlock }>("/parent/makeup-request", {
      attendance_id: attendanceId,
    });
    return data.makeup;
  });

  const submit = async (row: MakeupAbsence) => {
    setRequesting(row.attendance_id);
    const created = await request.run(row.attendance_id);
    setRequesting(null);
    // 신청 결과는 표의 상태 뱃지로 바로 보인다 — 토스트는 띄우지 않는다.
    if (created) await home.reload();
  };

  const absences = home.data?.absences ?? [];
  const started = home.data?.calendar != null;
  const openCount = requestableCount(absences);

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
      ) : !enrolled ? (
        <PreEnrollNotice
          child={child}
          what="보강 영상 신청"
          why="결석한 수업이 있어야 보강 영상을 신청할 수 있습니다."
        />
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
            aside={
              absences.length > 0
                ? openCount > 0
                  ? `신청할 수 있는 결석 ${openCount}건`
                  : "모두 처리됨"
                : undefined
            }
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
            padding={absences.length > 0 ? "none" : "md"}
          >
            {!started ? (
              <EmptyState
                title="아직 수업이 시작되지 않았습니다"
                description="등록이 확정되고 수업이 시작되면 결석 기록과 보강 영상 신청이 여기에 열립니다."
              />
            ) : absences.length === 0 ? (
              <EmptyState
                title={`${monthLabel(month)}에는 결석이 없습니다`}
                description="다른 달을 보려면 위의 달 이동 단추를 눌러 주세요."
              />
            ) : (
              <AbsenceRequestTable
                rows={absences}
                formatDate={dayLabel}
                onRequest={submit}
                pendingId={requesting}
                caption="결석일과 보강 영상 신청 상태"
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
            <p className="parent-note parent-note--spaced">
              이미 신청했거나 지급된 결석에는 신청 단추가 나타나지 않습니다. 거절된 신청은 사유를
              확인한 뒤 다시 신청할 수 있습니다.
            </p>
          </Card>
        </div>
      )}
    </>
  );
}

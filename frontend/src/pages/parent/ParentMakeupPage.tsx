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
import { Alert, Button, Card, EmptyState, ErrorState, Loading, ScopeBar } from "../../components";
import { AbsenceRequestTable } from "../../features/makeup/AbsenceRequestTable";
import { MakeupAbsence, requestableCount } from "../../features/makeup/absences";
import { NO_CHILD_TITLE, useChild } from "./childContext";
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
      {picker && <ScopeBar>{picker}</ScopeBar>}

      {studentId === null ? (
        <Card padding="none">
          <EmptyState title={NO_CHILD_TITLE} />
        </Card>
      ) : !enrolled ? (
        <PreEnrollNotice child={child} what="보강 영상 신청" />
      ) : home.loading ? (
        <Loading label="결석한 수업을 불러오는 중…" />
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
            padding="none"
          >
            {!started ? (
              <EmptyState title="아직 수업이 시작되지 않았습니다" />
            ) : absences.length === 0 ? (
              <EmptyState title={`${monthLabel(month)}에는 결석이 없습니다`} />
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
        </div>
      )}
    </>
  );
}

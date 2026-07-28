/**
 * 학생 동보 신청 — POST /api/student/makeup-request {attendance_id} (PRD 3.2.3)
 *
 * 결석 목록과 진행 상태는 GET /api/student/home 의 calendar.days 에서 온다 —
 * 서버가 날짜마다 attendance_id·makeup_status 를 함께 내려주므로(2026-07-28 보강)
 * 학생은 결석한 날의 버튼을 한 번 누르는 것으로 신청이 끝난다.
 * 출결 번호를 사람이 옮겨 적던 우회 입력은 제거했다.
 *
 * 신청 대상 판정은 features/makeup/absences.ts 한 곳에만 둔다(학부모 화면과 공유).
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
import { MakeupAbsence, absencesFromDays, requestableCount } from "../../features/makeup/absences";
import {
  MakeupResult,
  StudentHome,
  currentMonth,
  dayLabel,
  monthLabel,
  shiftMonth,
} from "./lib";
import "./student.css";

export default function StudentMakeupPage() {
  const [month, setMonth] = useState(currentMonth());
  const [pendingId, setPendingId] = useState<number | null>(null);
  const [result, setResult] = useState<MakeupResult | null>(null);

  const home = useApi(
    () => http.get<StudentHome>("/student/home", { params: { month } }).then((r) => r.data),
    [month],
  );

  const submit = useApiAction(async (attendanceId: number) => {
    const response = await http.post<{ makeup: MakeupResult }>("/student/makeup-request", {
      attendance_id: attendanceId,
    });
    return response.data.makeup;
  });

  const absences = absencesFromDays(home.data?.calendar?.days ?? []);
  const openCount = requestableCount(absences);

  const request = async (row: MakeupAbsence) => {
    setResult(null);
    setPendingId(row.attendance_id);
    const created = await submit.run(row.attendance_id);
    setPendingId(null);
    if (!created) return; // 실패 사유는 카드 위 Alert 로 보인다
    setResult(created);
    await home.reload();
  };

  return (
    <>
      <PageHeader title="동보 신청" />

      <div className="ui-stack">
        {submit.error && (
          <Alert tone="danger" onClose={submit.clearError}>
            {submit.error}
          </Alert>
        )}

        {result && (
          <Alert tone="success" onClose={() => setResult(null)}>
            {result.session_date ? dayLabel(result.session_date) : "해당 수업"} 결석 동보 신청
            {result.course_name && result.week_no !== null
              ? ` — ${result.course_name} ${result.week_no}주차`
              : ""}{" "}
            · <b>{result.status}</b>
          </Alert>
        )}

        <Card
          title={`${monthLabel(month)} 결석한 수업`}
          aside={
            home.data && absences.length > 0
              ? openCount > 0
                ? `신청할 수 있는 결석 ${openCount}건`
                : "모두 처리됨"
              : undefined
          }
          actions={
            <>
              <Button size="sm" onClick={() => setMonth(shiftMonth(month, -1))}>
                이전 달
              </Button>
              <Button size="sm" onClick={() => setMonth(shiftMonth(month, 1))}>
                다음 달
              </Button>
            </>
          }
          padding={absences.length > 0 ? "none" : "md"}
        >
          {home.loading ? (
            <Loading label="출결을 불러오는 중…" />
          ) : home.error ? (
            <ErrorState description={home.error} onRetry={home.reload} />
          ) : absences.length === 0 ? (
            <EmptyState title={`${monthLabel(month)}에는 결석한 수업이 없습니다`} />
          ) : (
            <AbsenceRequestTable
              rows={absences}
              formatDate={dayLabel}
              onRequest={request}
              pendingId={pendingId}
              caption="결석한 날과 동보 신청 상태"
            />
          )}
        </Card>

      </div>
    </>
  );
}

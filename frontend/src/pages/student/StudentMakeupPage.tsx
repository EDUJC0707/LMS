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
      <PageHeader
        title="동보 신청"
        description="결석한 수업의 복습영상을 신청합니다. 승인되면 그 주차 영상을 볼 수 있는 권한이 지급됩니다."
      />

      <div className="ui-stack">
        {submit.error && (
          <Alert tone="danger" onClose={submit.clearError}>
            {submit.error}
          </Alert>
        )}

        {result && (
          <Alert tone="success" onClose={() => setResult(null)}>
            {result.session_date ? dayLabel(result.session_date) : "해당 수업"} 결석에 대한 동보를
            신청했습니다
            {result.course_name && result.week_no !== null
              ? ` — ${result.course_name} ${result.week_no}주차`
              : ""}
            . 지금은 <b>{result.status}</b> 상태이며, 승인되면 그 주차 복습영상 권한이 지급됩니다.
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
            <EmptyState
              title={`${monthLabel(month)}에는 결석한 수업이 없습니다`}
              description="동보는 결석한 수업에만 신청할 수 있습니다. 다른 달을 확인하려면 위의 달 이동 버튼을 눌러 주세요."
            />
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

        <Card title="신청하면 이렇게 진행됩니다">
          <ol className="st-steps">
            <li>
              <strong>신청</strong> — 결석한 수업의 복습영상을 요청합니다.
            </li>
            <li>
              <strong>승인</strong> — 학원이 결석 사유와 수업 회차를 확인합니다.
            </li>
            <li>
              <strong>지급완료</strong> — 영상이 열리고, 시청 기한이 홈의 &lsquo;곧 마감되는
              것&rsquo;에 나타납니다.
            </li>
          </ol>
          <p className="st-note" style={{ marginTop: "var(--space-sm)" }}>
            이미 신청했거나 지급된 결석에는 신청 버튼이 나타나지 않습니다. 거절된 신청은 사유를
            확인한 뒤 다시 신청할 수 있습니다.
          </p>
        </Card>
      </div>
    </>
  );
}

/**
 * 학생 동보 신청 — POST /api/student/makeup-request {attendance_id} (PRD 3.2.3)
 *
 * ⚠ API 갭(2026-07-28 실측): 소비자 API 어디에서도 결석의 attendance_id 를
 *   내려주지 않는다. /api/student/home 의 calendar.days 는 date·attendance·
 *   has_class_session 만 준다(백엔드 apps/curriculum/home.py). 그래서 화면은
 *   ① 홈에서 읽어온 결석일을 그대로 보여주고
 *   ② 신청에는 출결 번호(attendance_id) 를 직접 입력받는다.
 *   이 사실을 감추지 않고 화면에 그대로 적는다. 서버가 안 주는 값을 추측해
 *   만들어내지 않는다(PRD §4 상태 기반 노출).
 */
import { FormEvent, useState } from "react";

import { http, useApi, useApiAction } from "../../api";
import {
  Alert,
  Button,
  Card,
  EmptyState,
  ErrorState,
  Field,
  Input,
  Loading,
  PageHeader,
} from "../../components";
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
  const [attendanceId, setAttendanceId] = useState("");
  const [touched, setTouched] = useState(false);
  const [result, setResult] = useState<MakeupResult | null>(null);

  const home = useApi(
    () => http.get<StudentHome>("/student/home", { params: { month } }).then((r) => r.data),
    [month],
  );

  const submit = useApiAction(async (id: number) => {
    const response = await http.post<{ makeup: MakeupResult }>("/student/makeup-request", {
      attendance_id: id,
    });
    return response.data.makeup;
  });

  const absentDays = (home.data?.calendar?.days ?? [])
    .filter((day) => day.attendance === "결석")
    .map((day) => day.date);

  const parsed = Number(attendanceId);
  const idError =
    touched && attendanceId.trim() !== "" && (!Number.isInteger(parsed) || parsed <= 0)
      ? "출결 번호는 숫자로 입력해 주세요."
      : null;

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setTouched(true);
    if (!Number.isInteger(parsed) || parsed <= 0) return;
    setResult(null);
    const created = await submit.run(parsed);
    if (created) {
      setResult(created);
      setAttendanceId("");
      setTouched(false);
    }
  };

  return (
    <>
      <PageHeader
        title="동보 신청"
        description="결석한 수업의 복습영상을 신청합니다. 승인되면 그 주차 영상을 볼 수 있는 권한이 지급됩니다."
      />

      <div className="ui-stack">
        <Card
          title={`${monthLabel(month)} 결석일`}
          aside="출결 기록 기준"
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
        >
          {home.loading ? (
            <Loading label="출결을 불러오는 중…" />
          ) : home.error ? (
            <ErrorState description={home.error} onRetry={home.reload} />
          ) : absentDays.length === 0 ? (
            <EmptyState
              title={`${monthLabel(month)}에는 결석한 수업이 없습니다`}
              description="다른 달을 확인하려면 위의 달 이동 버튼을 눌러 주세요. 동보는 결석한 수업에만 신청할 수 있습니다."
            />
          ) : (
            <>
              <ul className="st-absent">
                {absentDays.map((date) => (
                  <li key={date} className="st-absent__day">
                    {dayLabel(date)}
                  </li>
                ))}
              </ul>
              <p className="st-note" style={{ marginTop: "var(--space-md)" }}>
                이 날짜의 수업이 동보 신청 대상입니다. 이미 신청했거나 지급된 결석은 다시 신청할
                수 없습니다.
              </p>
            </>
          )}
        </Card>

        <Card title="동보 신청">
          <Alert tone="info">
            지금은 결석일의 <b>출결 번호</b>를 직접 입력해야 신청할 수 있습니다. 번호는 담당
            선생님이나 학원 데스크에서 확인할 수 있습니다. 화면에서 결석일을 눌러 바로 신청하는
            방식은 준비 중입니다.
          </Alert>

          <form onSubmit={onSubmit} style={{ marginTop: "var(--space-md)", maxWidth: "22rem" }}>
            <Field
              label="출결 번호"
              required
              hint="결석한 수업의 출결 기록 번호입니다."
              error={idError ?? submit.error}
            >
              {(props) => (
                <Input
                  {...props}
                  inputMode="numeric"
                  placeholder="1234"
                  value={attendanceId}
                  onBlur={() => setTouched(true)}
                  onChange={(event) => {
                    setAttendanceId(event.target.value);
                    if (submit.error) submit.clearError();
                  }}
                />
              )}
            </Field>
            <Button type="submit" variant="primary" loading={submit.pending}>
              동보 신청
            </Button>
          </form>

          {result && (
            <div style={{ marginTop: "var(--space-md)" }}>
              <Alert tone="success" onClose={() => setResult(null)}>
                {result.session_date ? dayLabel(result.session_date) : "해당 수업"} 결석에 대한
                동보를 신청했습니다
                {result.course_name && result.week_no !== null
                  ? ` — ${result.course_name} ${result.week_no}주차`
                  : ""}
                . 지금은 <b>{result.status}</b> 상태이며, 승인되면 그 주차 복습영상 권한이
                지급됩니다.
              </Alert>
            </div>
          )}
        </Card>
      </div>
    </>
  );
}

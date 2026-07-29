/**
 * 오늘 운영 대시보드 — 수업 당일 "지금 뭘 해야 하나"를 한 화면에 모은다.
 *
 * 호출: GET /api/admin/attendance/sessions · .../sessions/{id}
 *      · GET /api/admin/makeup-requests?status=신청
 *      · GET /api/admin/clinic/requests?status=대기
 *      · GET /api/admin/counseling/queue
 *      · GET /api/admin/workbook
 *
 * 권한 없는 항목은 회색 처리가 아니라 **호출도 렌더도 하지 않는다**(PRD §4).
 * 조교 계정은 기능 키가 둘뿐이라 이 화면이 실제로 두 칸으로 줄어든다.
 */
import { ReactNode } from "react";
import { Link } from "react-router-dom";

import { http, useApi } from "../../../api";
import type { ApiState } from "../../../api";
import { useMe } from "../../../auth";
import { Button, Card, EmptyState, ErrorState, Loading, Spinner } from "../../../components";
import { Fig } from "./Fig";
import { relativeDay, sessionLabel, shortDate, todayISO } from "./format";
import "./ops.css";
import type {
  ClinicRequestRow,
  CounselCard,
  MakeupRow,
  SessionBlock,
  SessionDetail,
  WorkbookListResponse,
} from "./types";

export default function AdminDashboardPage() {
  const { hasFeature } = useMe();
  const today = todayISO();

  const canAttendance = hasFeature("출결입력");
  const canMakeup = hasFeature("영상지급관리");
  const canClinic = hasFeature("클리닉배정");
  const canCounsel = hasFeature("상담기록");
  const canWorkbook = hasFeature("워크북업로드");

  const sessions = useApi<SessionBlock[] | null>(
    async () =>
      canAttendance
        ? (await http.get<{ sessions: SessionBlock[] }>("/admin/attendance/sessions")).data
            .sessions
        : null,
    [canAttendance],
  );

  const all = sessions.data ?? [];
  const todays = all.filter((s) => s.session_date === today);
  const previous = [...all].reverse().find((s) => s.session_date < today) ?? null;
  const upcoming = all.find((s) => s.session_date > today) ?? null;
  // 오늘 수업이 있으면 그것이, 없으면 직전 수업이 지금 손댈 회차다.
  const focus = todays.length > 0 ? todays : previous ? [previous] : [];
  const focusKey = focus.map((s) => s.session_id).join(",");

  const details = useApi<SessionDetail[] | null>(
    async () =>
      focusKey
        ? await Promise.all(
            focusKey
              .split(",")
              .map((id) =>
                http.get<SessionDetail>(`/admin/attendance/sessions/${id}`).then((r) => r.data),
              ),
          )
        : null,
    [focusKey],
  );

  const makeup = useApi<number | null>(
    async () =>
      canMakeup
        ? (
            await http.get<{ requests: MakeupRow[] }>("/admin/makeup-requests", {
              params: { status: "신청" },
            })
          ).data.requests.length
        : null,
    [canMakeup],
  );

  const clinic = useApi<number | null>(
    async () =>
      canClinic
        ? (
            await http.get<{ requests: ClinicRequestRow[] }>("/admin/clinic/requests", {
              params: { status: "대기" },
            })
          ).data.requests.length
        : null,
    [canClinic],
  );

  const counseling = useApi<number | null>(
    async () =>
      canCounsel
        ? (await http.get<{ queue: CounselCard[] }>("/admin/counseling/queue")).data.queue.length
        : null,
    [canCounsel],
  );

  const workbook = useApi<number | null>(
    async () =>
      canWorkbook
        ? (await http.get<WorkbookListResponse>("/admin/workbook")).data.unmatched_count
        : null,
    [canWorkbook],
  );

  const tiles: ReactNode[] = [];
  if (canMakeup)
    tiles.push(
      <OpsTile
        key="makeup"
        to="/admin/makeup"
        label="동보 승인 대기"
        state={makeup}
      />,
    );
  if (canCounsel)
    tiles.push(
      <OpsTile
        key="counseling"
        to="/admin/counseling"
        label="결석 상담 대기"
        state={counseling}
      />,
    );
  if (canClinic)
    tiles.push(
      <OpsTile
        key="clinic"
        to="/admin/clinic"
        label="클리닉 배정 대기"
        state={clinic}
      />,
    );
  if (canWorkbook)
    tiles.push(
      <OpsTile
        key="workbook"
        to="/admin/workbook"
        label="워크북 매칭 잔량"
        state={workbook}
        unit="장"
      />,
    );

  // 옛 페이지 설명(`날짜 · 이름 역할`)은 지웠다 — 이름·역할은 계정 칩이,
  // 회차 날짜는 아래 회차 줄이 이미 말한다.
  return (
    <div className="ui-stack">
      {canAttendance && (
        <Card
          title={todays.length > 0 ? "오늘 수업" : "직전 수업"}
          aside={
            upcoming
              ? `다음 수업 ${shortDate(upcoming.session_date)} · ${relativeDay(upcoming.session_date, today)}`
              : undefined
          }
        >
          {sessions.loading || details.loading ? (
            <div className="ops-cardstate">
              <Loading label="회차를 불러오는 중…" />
            </div>
          ) : sessions.error ? (
            <div className="ops-cardstate">
              <ErrorState description={sessions.error} onRetry={sessions.reload} />
            </div>
          ) : details.error ? (
            <div className="ops-cardstate">
              <ErrorState description={details.error} onRetry={details.reload} />
            </div>
          ) : (details.data ?? []).length === 0 ? (
            <div className="ops-cardstate">
              <EmptyState title="등록된 수업 회차가 없습니다" />
            </div>
          ) : (
            <div className="ui-stack ui-stack--md">
              {(details.data ?? []).map((detail) => (
                <SessionRow key={detail.session.session_id} detail={detail} today={today} />
              ))}
            </div>
          )}
        </Card>
      )}

      {/* 위 카드와 같은 위계다 — 면(그림자)도 안쪽 여백도 같은 값을 쓴다.
          전에는 flat + padding="sm" 이라 타일이 카드 제목보다 8px 왼쪽에서
          시작했고, 카드 하나만 종이에서 떠 있지 않았다. */}
      {tiles.length > 0 && (
        <Card title="처리 대기">
          <div className="ops-tiles">{tiles}</div>
        </Card>
      )}

      {!canAttendance && tiles.length === 0 && (
        <Card>
          <div className="ops-cardstate">
            <EmptyState title="지금 계정에는 운영 화면 권한이 없습니다" />
          </div>
        </Card>
      )}
    </div>
  );
}

function SessionRow({ detail, today }: { detail: SessionDetail; today: string }) {
  const { session, summary } = detail;
  const untouched = summary.미입력 === summary.total;

  return (
    <div className="ops-focus">
      <div className="ops-id">
        <span className="ops-id__title">
          {shortDate(session.session_date)} {sessionLabel(session)}
        </span>
        <span className="ops-id__meta">
          {relativeDay(session.session_date, today)} 수업 · 명단 {summary.total}명
          {session.memo ? ` · ${session.memo}` : ""}
        </span>
      </div>

      <div className="ops-figs">
        <Fig tone="present" n={summary.출석} label="출석" />
        <Fig tone="absent" n={summary.결석} label="결석" />
        <Fig tone="makeup" n={summary["결석(동보)"]} label="동보" />
        <Fig tone="onsite" n={summary["결석(현보)"]} label="현보" />
        <Fig tone="blank" n={summary.미입력} label="미입력" />
      </div>

      <Link to={`/admin/attendance/${session.session_id}`}>
        <Button variant={summary.미입력 > 0 ? "primary" : "secondary"}>
          {untouched ? "출결 입력하기" : summary.미입력 > 0 ? "이어서 입력" : "출결 확인"}
        </Button>
      </Link>
    </div>
  );
}

function OpsTile({
  to,
  label,
  state,
  unit = "건",
}: {
  to: string;
  label: string;
  state: ApiState<number | null>;
  unit?: string;
}) {
  const count = state.data ?? 0;
  return (
    <Link to={to} className="ops-tile">
      <span className="ops-tile__label">{label}</span>
      <span className="ops-tile__value">
        {state.loading ? (
          <Spinner size="sm" label={`${label} 건수를 불러오는 중`} />
        ) : state.error ? (
          <span className="ops-tile__unit">지금은 확인할 수 없습니다</span>
        ) : (
          <>
            <span className={`ops-tile__n num ${count === 0 ? "is-zero" : ""}`.trim()}>{count}</span>
            <span className="ops-tile__unit">{unit}</span>
          </>
        )}
      </span>
    </Link>
  );
}

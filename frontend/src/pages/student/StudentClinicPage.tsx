/**
 * 학생 클리닉 신청 — PRD 3.2.4
 *   GET   /api/student/clinic?exam_id=
 *   POST  /api/student/clinic/requests            {exam_id, slot_id, requested_date}
 *   PATCH /api/student/clinic/requests/{id}       {slot_id, requested_date}
 *   POST  /api/student/clinic/requests/{id}/cancel
 *
 * 상태 기반 노출: 대상자가 아니면 서버가 slots 자체를 안 내려준다 → 신청 UI 를
 * 회색으로 두는 게 아니라 화면에 만들지 않는다.
 * 규칙 위반(마감·당일 8시·노쇼 제한·중복)은 서버가 문장으로 돌려주므로
 * 그 문장을 그대로 사람에게 보여준다(우리가 다시 쓰지 않는다).
 */
import { useEffect, useState } from "react";

import { http, useApi, useApiAction } from "../../api";
import {
  Alert,
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  Loading,
  Modal,
  PageHeader,
  Radio,
  Select,
  StatusBadge,
  Table,
} from "../../components";
import {
  ClinicPayload,
  ClinicRequestRow,
  ClinicSlot,
  GradeList,
  dayLabel,
  weekdayName,
} from "./lib";
import "./student.css";

/** 변경·취소가 가능한 상태(백엔드 ACTIVE_STATUSES 와 동일). */
const ACTIVE = ["대기", "승인배정"];

export default function StudentClinicPage() {
  const [examId, setExamId] = useState<number | null>(null);
  const [changing, setChanging] = useState<ClinicRequestRow | null>(null);
  const [cancelling, setCancelling] = useState<ClinicRequestRow | null>(null);
  const [pickedSlot, setPickedSlot] = useState<number | null>(null);

  const grades = useApi(() => http.get<GradeList>("/student/grades").then((r) => r.data), []);
  const exams = grades.data?.exams ?? [];
  const effectiveExamId = examId ?? (exams.length > 0 ? exams[exams.length - 1].exam_id : null);

  const clinic = useApi(
    () =>
      effectiveExamId === null
        ? Promise.resolve(null)
        : http
            .get<ClinicPayload>("/student/clinic", { params: { exam_id: effectiveExamId } })
            .then((r) => r.data),
    [effectiveExamId],
  );

  const book = useApiAction(async (slot: ClinicSlot) => {
    await http.post("/student/clinic/requests", {
      exam_id: effectiveExamId,
      slot_id: slot.slot_id,
      requested_date: slot.next_date,
    });
    await clinic.reload();
  });

  const change = useApiAction(async (row: ClinicRequestRow, slot: ClinicSlot) => {
    await http.patch(`/student/clinic/requests/${row.clinic_id}`, {
      slot_id: slot.slot_id,
      requested_date: slot.next_date,
    });
    await clinic.reload();
    setChanging(null);
  });

  const cancel = useApiAction(async (row: ClinicRequestRow) => {
    await http.post(`/student/clinic/requests/${row.clinic_id}/cancel`);
    await clinic.reload();
    setCancelling(null);
  });

  // 모달을 새로 열 때마다 이전 에러·선택을 지운다.
  useEffect(() => {
    if (changing) {
      setPickedSlot(changing.slot_id);
      change.clearError();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [changing]);

  useEffect(() => {
    if (cancelling) cancel.clearError();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cancelling]);

  const loading = grades.loading || clinic.loading;
  const error = grades.error ?? clinic.error;

  if (loading) {
    return (
      <>
        <PageHeader title="클리닉 신청" />
        <Loading label="신청 가능한 시간대를 불러오는 중…" />
      </>
    );
  }

  if (error) {
    return (
      <>
        <PageHeader title="클리닉 신청" />
        <ErrorState
          description={error}
          onRetry={() => {
            void grades.reload();
            void clinic.reload();
          }}
        />
      </>
    );
  }

  const data = clinic.data;

  if (!data) {
    return (
      <>
        <PageHeader
          title="클리닉 신청"
          description="시험 결과에 따라 배정되는 1:1 온라인 클리닉을 신청합니다."
        />
        <Card>
          <EmptyState
            title="아직 클리닉을 신청할 시험이 없습니다"
            description="시험을 응시하고 성적이 확정되면, 대상자에게 신청 가능한 시간대가 열립니다."
          />
        </Card>
      </>
    );
  }

  const slots = data.slots ?? [];
  const active = data.my_requests.filter((row) => ACTIVE.includes(row.status));
  // 신청 버튼을 회색으로 남기지 않는다 — 지금 신청할 수 없는 이유를 문장으로 말하고
  // 버튼 자체를 화면에서 뺀다(PRD §4 상태 기반 노출).
  const blocked: string | null = data.clinic_banned
    ? "신청이 제한된 상태라 새로 신청할 수 없습니다. 이미 신청한 건의 취소는 가능합니다."
    : active.length > 0
      ? "이미 신청한 클리닉이 있습니다. 한 시험에 한 건까지 신청할 수 있어요 — 시간을 바꾸려면 아래 내 신청 현황에서 변경하세요."
      : null;

  return (
    <>
      <PageHeader
        title="클리닉 신청"
        description="시험 결과에 따라 배정되는 1:1 온라인 클리닉입니다. 시간대를 고르면 담당 선생님 배정 후 미트 링크가 열립니다."
        actions={
          exams.length > 1 ? (
            <Select
              aria-label="대상 시험 선택"
              value={effectiveExamId ?? ""}
              onChange={(event) => setExamId(Number(event.target.value))}
            >
              {exams.map((exam) => (
                <option key={exam.exam_id} value={exam.exam_id}>
                  {exam.name}
                </option>
              ))}
            </Select>
          ) : undefined
        }
      />

      <div className="ui-stack">
        {data.clinic_banned && (
          <Alert tone="warning">
            노쇼가 누적되어 클리닉 신청이 제한된 상태입니다. 이미 신청한 건의 취소만 가능하며,
            제한 해제는 학원에 문의해 주세요.
          </Alert>
        )}

        {!data.eligibility.is_target ? (
          <Card title={data.exam.name} aside={data.exam.exam_date}>
            <EmptyState
              title="이번 회차는 클리닉 대상이 아닙니다"
              description={
                data.eligibility.reason
                  ? `사유 — ${data.eligibility.reason}`
                  : "클리닉은 회차별 성적 판정으로 대상자가 정해집니다. 다음 회차 판정 결과를 기다려 주세요."
              }
            />
          </Card>
        ) : (
          <Card
            title="신청 가능한 시간대"
            aside={`${data.exam.name} 기준`}
            padding="none"
          >
            {(book.error || blocked) && (
              <div style={{ padding: "var(--space-md) var(--space-lg) 0" }}>
                {book.error ? (
                  <Alert tone="danger" onClose={book.clearError}>
                    {book.error}
                  </Alert>
                ) : (
                  <Alert tone="info">{blocked}</Alert>
                )}
              </div>
            )}
            <Table<ClinicSlot>
              rows={slots}
              rowKey={(row) => row.slot_id}
              caption="신청 가능한 클리닉 시간대"
              empty="지금 열려 있는 시간대가 없습니다. 시간대가 추가되면 이곳에 표시됩니다."
              columns={[
                {
                  key: "when",
                  header: "요일 · 시간",
                  cell: (row) => (
                    <>
                      <span style={{ fontWeight: "var(--weight-medium)" }}>
                        {weekdayName(row.weekday)}요일 {row.start_time}~{row.end_time}
                      </span>
                      <span
                        style={{
                          display: "block",
                          fontSize: "var(--text-xs)",
                          color: "var(--color-muted)",
                        }}
                      >
                        가장 가까운 날짜 {dayLabel(row.next_date)}
                      </span>
                    </>
                  ),
                },
                {
                  key: "remaining",
                  header: "남은 자리",
                  align: "right",
                  numeric: true,
                  sortValue: (row) => row.remaining,
                  cell: (row) => `${row.remaining} / ${row.capacity}`,
                },
                {
                  key: "action",
                  header: "",
                  align: "right",
                  width: "8rem",
                  cell: (row) => {
                    if (row.is_full) return <Badge tone="neutral">마감</Badge>;
                    if (blocked) return null;
                    return (
                      <Button
                        size="sm"
                        variant="primary"
                        loading={book.pending}
                        onClick={() => void book.run(row)}
                      >
                        신청
                      </Button>
                    );
                  },
                },
              ]}
            />
            <div style={{ padding: "var(--space-md) var(--space-lg) var(--space-lg)" }}>
              <p className="st-note">
                {!blocked && "한 시험에 신청은 한 건까지입니다. "}
                당일 신청·변경·취소는 오전 8시까지만 가능하고, 그 이후에는 학원으로 연락해 주세요.
              </p>
            </div>
          </Card>
        )}

        <Card title="내 신청 현황" aside={`${data.my_requests.length}건`} padding="none">
          <Table<ClinicRequestRow>
            rows={data.my_requests}
            rowKey={(row) => row.clinic_id}
            caption="내 클리닉 신청 현황"
            empty="아직 신청한 클리닉이 없습니다. 위에서 시간대를 골라 신청하세요."
            columns={[
              {
                key: "when",
                header: "일시",
                cell: (row) => (
                  <>
                    <span style={{ fontWeight: "var(--weight-medium)" }}>
                      {dayLabel(row.requested_date)}
                    </span>
                    <span className="num" style={{ marginLeft: "var(--space-xs)" }}>
                      {row.requested_time}
                    </span>
                  </>
                ),
              },
              {
                key: "status",
                header: "상태",
                width: "8rem",
                cell: (row) => <StatusBadge status={row.status} />,
              },
              {
                key: "link",
                header: "미트 링크",
                cell: (row) =>
                  row.meet_url ? (
                    <a href={row.meet_url} target="_blank" rel="noreferrer">
                      클리닉 입장하기
                    </a>
                  ) : row.status === "승인배정" ? (
                    <span style={{ color: "var(--color-muted)" }}>시작 5분 전에 열립니다</span>
                  ) : (
                    <span style={{ color: "var(--color-neutral)" }}>—</span>
                  ),
              },
              {
                key: "action",
                header: "",
                align: "right",
                width: "11rem",
                cell: (row) =>
                  ACTIVE.includes(row.status) ? (
                    <span className="ui-row" style={{ justifyContent: "flex-end" }}>
                      {!data.clinic_banned && slots.length > 0 && (
                        <Button size="sm" onClick={() => setChanging(row)}>
                          시간 변경
                        </Button>
                      )}
                      <Button size="sm" variant="ghost" onClick={() => setCancelling(row)}>
                        취소
                      </Button>
                    </span>
                  ) : null,
              },
            ]}
          />
        </Card>
      </div>

      {/* 시간 변경 — 모달 안의 실패는 모달 안 Alert 로(토스트는 backdrop 아래로 가려진다) */}
      <Modal
        open={changing !== null}
        onClose={() => setChanging(null)}
        title="클리닉 시간 변경"
        footer={
          <>
            <Button onClick={() => setChanging(null)}>닫기</Button>
            <Button
              variant="primary"
              loading={change.pending}
              onClick={() => {
                const slot = slots.find((s) => s.slot_id === pickedSlot);
                if (changing && slot) void change.run(changing, slot);
              }}
            >
              이 시간으로 변경
            </Button>
          </>
        }
      >
        {change.error && <Alert tone="danger">{change.error}</Alert>}
        <p className="st-note" style={{ marginBottom: "var(--space-md)" }}>
          시간을 바꾸면 이미 배정된 선생님과 미트 링크는 회수되고 다시 대기 상태가 됩니다.
        </p>
        <fieldset className="st-slotpick">
          <legend className="sr-only">변경할 시간대 선택</legend>
          {slots.map((slot) => (
            <Radio
              key={slot.slot_id}
              name="clinic-slot"
              checked={pickedSlot === slot.slot_id}
              disabled={slot.is_full}
              onChange={() => setPickedSlot(slot.slot_id)}
              label={
                <>
                  {weekdayName(slot.weekday)}요일 {slot.start_time} · {dayLabel(slot.next_date)}
                  <span style={{ color: "var(--color-muted)" }}>
                    {" "}
                    남은 자리 {slot.remaining}
                    {slot.is_full ? " (마감)" : ""}
                  </span>
                </>
              }
            />
          ))}
        </fieldset>
      </Modal>

      {/* 취소 — 되돌릴 수 없으므로 확인을 받는다 */}
      <Modal
        open={cancelling !== null}
        onClose={() => setCancelling(null)}
        title="클리닉 신청을 취소할까요?"
        footer={
          <>
            <Button onClick={() => setCancelling(null)}>그대로 두기</Button>
            <Button
              variant="danger"
              loading={cancel.pending}
              onClick={() => {
                if (cancelling) void cancel.run(cancelling);
              }}
            >
              신청 취소
            </Button>
          </>
        }
      >
        {cancel.error && <Alert tone="danger">{cancel.error}</Alert>}
        {cancelling && (
          <p style={{ marginBottom: "var(--space-sm)" }}>
            <b>
              {dayLabel(cancelling.requested_date)}{" "}
              <span className="num">{cancelling.requested_time}</span>
            </b>{" "}
            클리닉 신청을 취소합니다.
          </p>
        )}
        <p className="st-note">
          취소는 노쇼로 집계되지 않습니다. 자리가 남아 있으면 다시 신청할 수 있습니다.
        </p>
      </Modal>
    </>
  );
}

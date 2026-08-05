/**
 * 학생 클리닉 예약 — 캘린들리형 2단 분할 (PRD 3.2.4)
 *
 *   GET   /api/student/clinic?exam_id=                          자격 · 내 신청
 *   GET   /api/student/clinic/availability?exam_id=&from=&to=   날짜별 가용 시간
 *   POST  /api/student/clinic/requests           {exam_id, slot_id, requested_date}
 *   PATCH /api/student/clinic/requests/{id}      {slot_id, requested_date}
 *   POST  /api/student/clinic/requests/{id}/cancel
 *
 * 좌 = 날짜(달력) · 우 = 그 날의 시간. 날짜를 고르고 시간 하나를 고르면
 * 그 칸이 반으로 접히면서 옆에 실행 버튼이 선다(캘린들리의 확인 제스처).
 *
 * 이 화면이 지키는 규칙은 하나다 — **정원·잔여석을 글자로 쓰지 않는다.**
 * 한 타임에 한 명이라 남은 자리는 늘 1이고, 그 사실은 칸의 생사로만 말한다:
 * 살아 있는 면 / 취소선 그어진 죽은 면 / 내 자리. 신청 창구의 끝도 같은
 * 어법이다 — 창구 밖 날짜는 죽은 칸, 창구 밖 달은 죽은 화살표.
 *
 * 시간표는 **한 번만 부른다**(from·to 없이). 창구가 [내일, 시험 주 다음
 * 월요일]이라 길어야 7일이고, 그 한 번의 응답이 달력이 걸칠 수 있는 달을
 * 전부 담는다 — 달을 넘길 때마다 서버를 다시 부를 이유가 없다.
 *
 * 규칙(마감·전날까지·창구·중복·노쇼 제한)은 전부 API 가 강제한다. 화면은 자격이
 * 없으면 시간표를 **부르지 않고**(availability 는 403), 실패하면 서버가 준
 * 문장을 고쳐 쓰지 않고 그대로 보여준다.
 */
import { useEffect, useRef, useState } from "react";

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
  ScopeBar,
  Select,
  StatusBadge,
} from "../../components";
import {
  AvailabilityTime,
  ClinicAvailability,
  ClinicPayload,
  ClinicRequestRow,
  GradeList,
  WEEKDAY_LABELS,
  calendarMonths,
  currentMonth,
  dayLabel,
  monthGrid,
  monthLabel,
  shiftMonth,
  timeColumn,
  windowClosed,
} from "./lib";
import type { TimeColumnView } from "./lib";
import "./clinic.css";

/** 변경·취소가 가능한 상태(백엔드 ACTIVE_STATUSES 와 동일). */
const ACTIVE = ["대기", "승인배정"];

/** 로컬 오늘(UTC 파싱으로 하루 밀리지 않게 직접 만든다). */
function todayIso(): string {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${month}-${day}`;
}

function monthOf(iso: string): string {
  return iso.slice(0, 7);
}

function Chevron({ dir }: { dir: "left" | "right" }) {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path
        d={dir === "left" ? "M10 3.5 5.5 8l4.5 4.5" : "M6 3.5 10.5 8 6 12.5"}
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/* ═══ 좌 · 달력 ═══════════════════════════════════════════════════════
   "이 날짜가 days 에 있나"로만 생사를 판정한다 — 지난 날·오늘·
   슬롯 없는 요일을 죽이는 로직을 화면이 따로 갖지 않는다(계약이 곧 그림). */

function MonthCalendar({
  month,
  first,
  last,
  open,
  selected,
  onMonth,
  onSelect,
  busy,
}: {
  month: string;
  /** 창구가 걸친 양 끝 달 — 그 밖으로 나가는 화살표는 죽인다. */
  first: string;
  last: string;
  open: Set<string>;
  selected: string | null;
  onMonth: (delta: number) => void;
  /** 없으면 달력은 읽기 전용이다(예약 후 — 내 날짜만 가리킨다). */
  onSelect?: (date: string) => void;
  busy: boolean;
}) {
  const today = todayIso();
  const cells = monthGrid(month).flat();

  return (
    <div className="cl-cal">
      <div className="cl-cal__head">
        <p className="cl-cal__month">{monthLabel(month)}</p>
        <button
          type="button"
          className="cl-nav"
          aria-label="이전 달"
          disabled={month <= first}
          onClick={() => onMonth(-1)}
        >
          <Chevron dir="left" />
        </button>
        <button
          type="button"
          className="cl-nav"
          aria-label="다음 달"
          disabled={month >= last}
          onClick={() => onMonth(1)}
        >
          <Chevron dir="right" />
        </button>
      </div>

      <div className={`cl-cal__grid${busy ? " cl-busy" : ""}`}>
        {WEEKDAY_LABELS.map((label) => (
          <div className="cl-cal__wd" key={label}>
            {label}
          </div>
        ))}
        {cells.map((iso, index) => {
          if (iso === null) return <div className="cl-day" key={`pad-${index}`} />;
          const isOpen = open.has(iso);
          const isOn = selected === iso;
          const clickable = isOpen && onSelect !== undefined;
          return (
            <div className="cl-day" key={iso}>
              <button
                type="button"
                className={[
                  "cl-day__btn",
                  isOpen ? "cl-day__btn--open" : "",
                  isOn ? "cl-day__btn--on" : "",
                  iso === today ? "cl-day__btn--today" : "",
                ]
                  .filter(Boolean)
                  .join(" ")}
                disabled={!clickable}
                aria-pressed={clickable ? isOn : undefined}
                onClick={clickable ? () => onSelect(iso) : undefined}
              >
                {Number(iso.slice(8))}
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ═══ 우 · 그 날의 시간 ═══════════════════════════════════════════════ */

function TimeColumn({
  view,
  picked,
  pending,
  changingFrom,
  busy,
  onPick,
  onConfirm,
  onBack,
}: {
  view: TimeColumnView;
  picked: number | null;
  pending: boolean;
  /** 변경 중이면 "어디서 옮기는 중인지"가 스크롤해도 남는다. */
  changingFrom: ClinicRequestRow | null;
  busy: boolean;
  onPick: (slotId: number | null) => void;
  onConfirm: (time: AvailabilityTime) => void;
  onBack: () => void;
}) {
  return (
    <div className="cl-times">
      {changingFrom && (
        <div className="cl-from">
          <span>변경 전</span>
          <span className="cl-from__when">
            {dayLabel(changingFrom.requested_date)}{" "}
            <span className="num">{changingFrom.requested_time}</span>
          </span>
          <Button size="sm" variant="ghost" className="cl-from__back" onClick={onBack}>
            돌아가기
          </Button>
        </div>
      )}

      {view.kind === "no-date" ? (
        <p className="cl-times__none">열려 있는 시간이 없습니다</p>
      ) : view.kind === "closed" ? (
        // 고른 날짜가 응답 밖이다 — 전날 마감으로 빠진 오늘이 여기 온다(오늘로
        // 잡힌 예약에서 [시간 변경]). 날짜만 쓰고 아래를 비우면 눌렀는데
        // 아무 말도 없는 화면이 된다.
        <>
          <p className="cl-times__head">{dayLabel(view.date)}</p>
          <p className="cl-times__none">열려 있는 시간이 없습니다</p>
        </>
      ) : (
        <>
          <p className="cl-times__head">{dayLabel(view.date)}</p>
          <div className={`cl-times__list${busy ? " cl-busy" : ""}`}>
            {view.times.map((time) => {
              if (picked === time.slot_id) {
                return (
                  <div className="cl-slot" key={time.slot_id}>
                    <button
                      type="button"
                      className="cl-time cl-time--picked"
                      aria-pressed="true"
                      onClick={() => onPick(null)}
                    >
                      {time.start_time}
                    </button>
                    <Button
                      variant="primary"
                      className="cl-slot__go"
                      loading={pending}
                      onClick={() => onConfirm(time)}
                    >
                      {changingFrom ? "변경" : "신청"}
                    </Button>
                  </div>
                );
              }
              const mine = !time.available && time.reason === "내신청";
              return (
                <div className="cl-slot" key={time.slot_id}>
                  <button
                    type="button"
                    className={[
                      "cl-time",
                      !time.available && !mine ? "cl-time--dead" : "",
                      mine ? "cl-time--mine" : "",
                    ]
                      .filter(Boolean)
                      .join(" ")}
                    disabled={!time.available}
                    onClick={time.available ? () => onPick(time.slot_id) : undefined}
                  >
                    {time.start_time}
                    {mine ? (
                      <span className="cl-time__tag">내 신청</span>
                    ) : (
                      !time.available && <span className="sr-only">{time.reason}</span>
                    )}
                  </button>
                </div>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}

/* ═══ 화면 ═══════════════════════════════════════════════════════════ */

export default function StudentClinicPage() {
  const [examId, setExamId] = useState<number | null>(null);
  /** null = 아직 학생이 달을 넘기지 않았다 → 고를 게 있는 첫 달을 연다. */
  const [month, setMonth] = useState<string | null>(null);
  const [day, setDay] = useState<string | null>(null);
  const [picked, setPicked] = useState<number | null>(null);
  const [changing, setChanging] = useState(false);
  const [cancelling, setCancelling] = useState<ClinicRequestRow | null>(null);
  const [done, setDone] = useState<string | null>(null);

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

  // useApi 는 재조회 중에도 직전 data 를 들고 있다. 회차를 바꾸면 새 판정이
  // 도착하기 전까지 옛 회차의 is_target 이 남아, 대상이 아닌 회차로도
  // availability 가 한 번 나가 403 을 맞는다(자격 없는 회차에서 시간표를
  // 부르지 않는다는 계약 위반). 판정은 **이 회차의 것일 때만** 유효로 친다.
  const judged = clinic.data?.exam.exam_id === effectiveExamId ? clinic.data : null;

  // 자격이 없거나 노쇼 제한이면 availability 는 403 이다 — 부르지 않는다.
  const canBook = Boolean(judged && judged.eligibility.is_target && !judged.clinic_banned);
  const active = judged?.my_requests.find((row) => ACTIVE.includes(row.status)) ?? null;

  // from·to 를 보내지 않는다 — 서버가 창구 전체(내일~시험 주 다음 월요일)를
  // 돌려주고, 그 한 번의 응답에 달력이 걸칠 수 있는 달이 전부 들어 있다.
  // 그래서 달을 넘겨도 다시 부르지 않고, 응답의 range 가 곧 창구의 양 끝이다
  // (달 단위로 잘라 물으면 잘린 끝과 창구의 끝을 구분할 수 없다).
  const avail = useApi(
    () =>
      effectiveExamId === null || !canBook
        ? Promise.resolve(null)
        : http
            .get<ClinicAvailability>("/student/clinic/availability", {
              params: { exam_id: effectiveExamId },
            })
            .then((r) => r.data),
    [effectiveExamId, canBook],
  );

  // useApiAction 의 run 은 첫 렌더의 클로저를 붙든다(useApi.ts 주석 참조).
  // 시험 번호와 재조회는 ref 로 최신값을 넘긴다 — 안 그러면 회차를 바꾼 뒤
  // 예전 회차로 신청이 나간다.
  const latest = useRef({ examId: effectiveExamId, refresh: async () => {} });
  latest.current.examId = effectiveExamId;
  latest.current.refresh = async () => {
    await Promise.all([clinic.reload(), avail.reload()]);
  };

  const book = useApiAction(async (date: string, time: AvailabilityTime) => {
    await http.post("/student/clinic/requests", {
      exam_id: latest.current.examId,
      slot_id: time.slot_id,
      requested_date: date,
    });
    setDone(`신청했습니다 — ${dayLabel(date)} ${time.start_time}`);
    setPicked(null);
    await latest.current.refresh();
  });

  const change = useApiAction(
    async (row: ClinicRequestRow, date: string, time: AvailabilityTime) => {
      await http.patch(`/student/clinic/requests/${row.clinic_id}`, {
        slot_id: time.slot_id,
        requested_date: date,
      });
      setDone(
        `변경했습니다 — ${dayLabel(row.requested_date)} ${row.requested_time} → ` +
          `${dayLabel(date)} ${time.start_time}`,
      );
      setChanging(false);
      setPicked(null);
      await latest.current.refresh();
    },
  );

  const cancel = useApiAction(async (row: ClinicRequestRow) => {
    await http.post(`/student/clinic/requests/${row.clinic_id}/cancel`);
    setDone(`취소했습니다 — ${dayLabel(row.requested_date)} ${row.requested_time}`);
    setCancelling(null);
    setChanging(false);
    await latest.current.refresh();
  });

  const days = avail.data?.days ?? [];

  // 응답이 바뀌면 고른 날짜를 다시 맞춘다 — 없어진 날에 머무르지 않고,
  // 처음 들어왔을 때 오른쪽 열이 비어 있지 않도록 가장 빠른 날을 연다.
  useEffect(() => {
    if (!avail.data) return;
    const list = avail.data.days;
    setDay((current) =>
      current && list.some((entry) => entry.date === current) ? current : (list[0]?.date ?? null),
    );
    setPicked(null);
  }, [avail.data]);

  if (grades.initialLoading || clinic.initialLoading) {
    return <Loading label="클리닉을 불러오는 중…" />;
  }

  const loadError = grades.error ?? clinic.error;
  if (loadError) {
    return (
      <ErrorState
        description={loadError}
        onRetry={() => {
          void grades.reload();
          void clinic.reload();
        }}
      />
    );
  }

  if (!clinic.data && !clinic.loading) {
    return (
      <Card padding="none">
        <EmptyState title="아직 클리닉을 신청할 시험이 없습니다" />
      </Card>
    );
  }

  // 카드 머리는 고른 회차를 곧바로 따른다 — 판정 응답을 기다리면 회차를 바꾼
  // 뒤에도 제목만 옛 회차로 남아 선택 상자와 어긋난다.
  const chosen = exams.find((exam) => exam.exam_id === effectiveExamId) ?? null;

  // 노쇼 제한 + 남은 신청도 없음 → 이 회차에 보여줄 판이 없다. 시간표는 403 이라
  // 달력을 세워 봐야 전부 죽은 칸이고, 우측 열은 "열려 있는 시간이 없습니다"라는
  // 틀린 말을 하게 된다(시간이 없는 게 아니라 계정이 막힌 것). 위의 경고 한 줄이
  // 이미 전부이므로 카드를 접는다.
  const blocked = Boolean(judged?.clinic_banned) && active === null;

  // 창구가 지났다 — 서버가 뒤집힌 구간으로 말해 준다(403 이 아니다).
  const closed = avail.data !== null && windowClosed(avail.data.range);
  // 달력이 설 달. 학생이 넘긴 달(month)이 있으면 그것을, 없으면 신청이 잡힌
  // 달을 힌트로 주고 — 어느 쪽이든 창구가 걸친 달 밖으로는 나가지 않는다.
  const cal = avail.data
    ? calendarMonths(avail.data, month ?? (active ? monthOf(active.requested_date) : null))
    : { month: currentMonth(), first: currentMonth(), last: currentMonth() };
  const shownMonth = cal.month;

  const column = timeColumn(days, day);
  const busy = avail.loading && !avail.initialLoading;
  const openDates = new Set(days.map((entry) => entry.date));
  // 종료 시각은 신청 응답에 없다 — 시간표에서 같은 슬롯을 찾아 붙인다.
  const activeEnd = active
    ? (days
        .flatMap((entry) => entry.times)
        .find((time) => time.slot_id === active.slot_id)?.end_time ?? null)
    : null;

  const startChange = () => {
    if (!active) return;
    change.clearError();
    setDone(null);
    setPicked(null);
    setDay(active.requested_date);
    setChanging(true);
  };

  const confirm = (time: AvailabilityTime) => {
    if (day === null) return;
    setDone(null);
    if (changing && active) void change.run(active, day, time);
    else void book.run(day, time);
  };

  const body = () => {
    // 회차를 막 바꿨다 — 옛 회차의 판정으로 그리면 대상이 아닌 회차에
    // 달력이 한 프레임 서고, 그 사이 availability 가 나간다.
    if (!judged) {
      return <Loading label="클리닉을 불러오는 중…" />;
    }
    if (!judged.eligibility.is_target) {
      return (
        <EmptyState
          title="이번 회차는 클리닉 대상이 아닙니다"
          description={
            judged.eligibility.reason ? (
              <Badge tone="neutral">{judged.eligibility.reason}</Badge>
            ) : undefined
          }
        />
      );
    }
    if (avail.initialLoading) {
      return <Loading label="예약 가능한 시간을 불러오는 중…" />;
    }
    if (avail.error) {
      return <ErrorState description={avail.error} onRetry={avail.reload} />;
    }

    const booked = active !== null && !changing;

    // 예약이 잡힌 뒤에는 달력을 세우지 않는다. 고를 게 없는데 한 달치 격자를
    // 그리면 칸 하나만 칠한 채 우측 열 아래로 빈 자리가 350px 남는다 —
    // 내용 없는 구조다. 캘린들리도 예약 후에는 달력 대신 확인 화면을 보인다.
    // [시간 변경]을 누르면 changing 이 서면서 달력이 돌아온다.
    if (booked && active) {
      return (
        <div className="cl-done">
          <div className="cl-booked__card">
            <StatusBadge status={active.status} />
            <p className="cl-booked__day">{dayLabel(active.requested_date)}</p>
            <p className="cl-booked__time">
              {active.requested_time}
              {activeEnd ? ` – ${activeEnd}` : ""}
            </p>
            {active.conference_url && (
              <div className="cl-booked__link">
                <a
                  className="ui-btn ui-btn--primary ui-btn--sm"
                  href={active.conference_url}
                  target="_blank"
                  rel="noreferrer"
                >
                  클리닉 입장
                </a>
              </div>
            )}
          </div>
          <div className="cl-booked__acts">
            {/* 창구가 지나면 옮겨 갈 날짜가 하나도 없다 — 눌러도 서버가 되돌려
                보낼 버튼은 세우지 않는다. 취소는 남긴다(반납은 창구 밖에서도
                받는다 — booking.py 취소 계약). */}
            {!judged.clinic_banned && !closed && (
              <Button size="sm" onClick={startChange}>
                시간 변경
              </Button>
            )}
            <Button size="sm" variant="ghost" onClick={() => setCancelling(active)}>
              취소
            </Button>
          </div>
        </div>
      );
    }

    // 창구가 지났다. 자격은 그대로이므로 "대상이 아닙니다"와 같은 화면을 보이면
    // 틀린 말이 되고, 달력을 세우면 전부 죽은 칸에 "열려 있는 시간이 없습니다"가
    // 붙어 **오늘 자리가 없는 것**처럼 읽힌다 — 다른 사실이므로 다른 화면이다.
    if (closed) {
      return <EmptyState title="클리닉 신청 기간이 끝났습니다" />;
    }

    return (
      <div className="cl-split">
        <MonthCalendar
          month={shownMonth}
          first={cal.first}
          last={cal.last}
          open={openDates}
          selected={day}
          onMonth={(delta) => setMonth(shiftMonth(shownMonth, delta))}
          onSelect={(date) => {
            setDay(date);
            setPicked(null);
          }}
          busy={busy}
        />

        <TimeColumn
          view={column}
          picked={picked}
          pending={book.pending || change.pending}
          changingFrom={changing ? active : null}
          busy={busy}
          onPick={(slotId) => {
            // 새로 고르기 시작하면 직전 결과 문장은 시효가 끝난다.
            setDone(null);
            setPicked(slotId);
          }}
          onConfirm={confirm}
          onBack={() => {
            setChanging(false);
            setPicked(null);
            change.clearError();
          }}
        />
      </div>
    );
  };

  return (
    <>
      {exams.length > 1 && (
        <ScopeBar>
          <Select
            aria-label="대상 시험 선택"
            value={effectiveExamId ?? ""}
            onChange={(event) => {
              setExamId(Number(event.target.value));
              setChanging(false);
              setPicked(null);
              setDone(null);
            }}
          >
            {exams.map((exam) => (
              <option key={exam.exam_id} value={exam.exam_id}>
                {exam.name}
              </option>
            ))}
          </Select>
        </ScopeBar>
      )}

      <div className="ui-stack">
        {judged?.clinic_banned && <Alert tone="warning">클리닉 신청이 제한된 계정입니다</Alert>}

        {done && (
          <Alert tone="success" onClose={() => setDone(null)}>
            {done}
          </Alert>
        )}

        {book.error && (
          <Alert tone="danger" onClose={book.clearError}>
            {book.error}
          </Alert>
        )}

        {change.error && (
          <Alert tone="danger" onClose={change.clearError}>
            {change.error}
          </Alert>
        )}

        {!blocked && (
          // 선택 상자가 있으면 회차명은 거기 있다 — 카드 머리가 같은 문장을
          // 반복하지 않는다. 회차가 하나뿐이면 여기가 유일한 이름 자리다.
          // 시험일(aside)은 예약하는 데 쓰이지 않아 뺐다.
          <Card title={exams.length > 1 ? undefined : chosen?.name} padding="none">
            {body()}
          </Card>
        )}
      </div>

      {/* 취소는 되돌릴 수 없다 — 확인을 받는다. */}
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
        <div className="ui-stack ui-stack--md">
          {cancel.error && <Alert tone="danger">{cancel.error}</Alert>}
          {cancelling && (
            <p>
              {dayLabel(cancelling.requested_date)}{" "}
              <b className="num">{cancelling.requested_time}</b>
            </p>
          )}
        </div>
      </Modal>
    </>
  );
}

/**
 * 학부모 홈 — GET /api/parent/home?student_id=&month=
 *
 * 학생 홈과 같은 캘린더(출결 도장·주차·마감)를 보되 **읽기 전용**이다.
 * 학부모에게만 내려오는 블록(교재 결제·이달 결석/동보)이 함께 붙는다.
 * 서버가 안 내려준 블록은 그리지 않는다(상태 기반 노출, PRD §4).
 */
import { useState } from "react";
import { Link } from "react-router-dom";

import { http, useApi } from "../../api";
import {
  Badge,
  Button,
  Card,
  DetailsPanel,
  EmptyState,
  ErrorState,
  Loading,
  ScopeBar,
  StatusBadge,
  Table,
} from "../../components";
import { NO_CHILD_TITLE, useChild } from "./childContext";
import {
  currentMonth,
  dDayLabel,
  dayLabel,
  monthLabel,
  money,
  shiftMonth,
  shortDay,
  weekdayName,
  withPrefix,
} from "./format";
import "./parent.css";
import {
  AbsenceRow,
  ClinicDeadline,
  Deadline,
  HomeDay,
  HomeWeek,
  ParentHome,
  PaymentDeadline,
  PaymentRow,
  VideoDeadline,
} from "./types";

export default function ParentHomePage() {
  const { studentId, picker } = useChild();
  const [month, setMonth] = useState(currentMonth());

  const home = useApi<ParentHome | null>(
    () =>
      studentId === null
        ? Promise.resolve(null)
        : http
            .get<ParentHome>("/parent/home", { params: { student_id: studentId, month } })
            .then((response) => response.data),
    [studentId, month],
  );

  return (
    <>
      {picker && <ScopeBar>{picker}</ScopeBar>}

      {studentId === null ? (
        <Card padding="none">
          <EmptyState title={NO_CHILD_TITLE} />
        </Card>
      ) : home.loading ? (
        <Loading label="이번 달 일정을 불러오는 중…" />
      ) : home.error ? (
        <ErrorState description={home.error} onRetry={home.reload} />
      ) : home.data ? (
        <HomeBody data={home.data} month={month} onMonth={setMonth} />
      ) : null}
    </>
  );
}

/* ── 본문 ───────────────────────────────────────────────────────── */

function HomeBody({
  data,
  month,
  onMonth,
}: {
  data: ParentHome;
  month: string;
  onMonth: (next: string) => void;
}) {
  const { student, course, calendar } = data;

  return (
    <div className="ui-stack">
      {/* 상단바는 "홈"만 말하고 계정 칩은 학부모 본인이다 — 누구를 보고 있는지는
          이 카드 제목이 든다(자녀가 1명이면 ScopeBar 조차 없다). */}
      <Card title={student.name} aside={student.current_class ?? "반 배정 전"}>
        <dl className="parent-facts">
          <div>
            <dt className="parent-facts__term">등록 상태</dt>
            <dd className="parent-facts__value">
              <StatusBadge status={student.enrollment_status} />
            </dd>
          </div>
          {course && (
            <>
              <div>
                <dt className="parent-facts__term">수강 과정</dt>
                <dd className="parent-facts__value">{course.name}</dd>
              </div>
              <div>
                <dt className="parent-facts__term">진도</dt>
                <dd className="parent-facts__value">
                  <span className="num">{course.current_week ?? "-"}</span> /{" "}
                  <span className="num">{course.total_weeks}</span>주차
                </dd>
              </div>
              <div>
                <dt className="parent-facts__term">수업 요일</dt>
                <dd className="parent-facts__value">
                  {course.class_weekdays.length === 0
                    ? "정해진 요일 없음"
                    : `${course.class_weekdays.map(weekdayName).join("·")}요일`}
                </dd>
              </div>
            </>
          )}
        </dl>
      </Card>

      {calendar ? (
        <>
          <MonthCard days={calendar.days} today={data.today} month={month} onMonth={onMonth} />
          {data.absences && <AbsenceCard rows={data.absences} />}
          <DeadlineCard rows={data.deadlines ?? []} />
          {data.payment_status && <PaymentCard rows={data.payment_status} />}
          <WeekCard weeks={calendar.weeks} />
        </>
      ) : (
        <NotEnrolled data={data} />
      )}
    </div>
  );
}

/* ── 캘린더 ─────────────────────────────────────────────────────── */

function MonthCard({
  days,
  today,
  month,
  onMonth,
}: {
  days: HomeDay[];
  today: string;
  month: string;
  onMonth: (next: string) => void;
}) {
  const byDate = new Map(days.map((day) => [day.date, day]));
  const recorded = days.filter((day) => day.attendance !== null);
  const attended = recorded.filter((day) => day.attendance === "출석").length;

  return (
    <Card
      title="이번 달 출결"
      aside={
        recorded.length > 0
          ? `기록된 ${recorded.length}일 중 출석 ${attended}일`
          : "아직 기록된 출결이 없습니다"
      }
      actions={
        <div className="parent-monthnav">
          <Button size="sm" onClick={() => onMonth(shiftMonth(month, -1))}>
            이전 달
          </Button>
          <span className="parent-monthnav__label">{monthLabel(month)}</span>
          <Button size="sm" onClick={() => onMonth(shiftMonth(month, 1))}>
            다음 달
          </Button>
        </div>
      }
    >
      <div className="parent-cal">
        {["일", "월", "화", "수", "목", "금", "토"].map((name) => (
          <div key={name} className="parent-cal__head">
            {name}
          </div>
        ))}
        {monthCells(month).map((date, index) => {
          if (date === null) {
            return (
              <div key={`blank-${index}`} className="parent-cal__cell parent-cal__cell--blank" />
            );
          }
          const info = byDate.get(date);
          const isToday = date === today;
          const classes = [
            "parent-cal__cell",
            info?.has_class_session ? "parent-cal__cell--class" : "",
            isToday ? "parent-cal__cell--today" : "",
          ]
            .filter(Boolean)
            .join(" ");
          return (
            <div key={date} className={classes}>
              <span className="parent-cal__date">
                <span className="num">{Number(date.slice(8))}</span>
                {isToday && <span className="parent-cal__today">오늘</span>}
              </span>
              {info?.attendance ? (
                <StatusBadge status={info.attendance} />
              ) : info?.has_class_session ? (
                <span className="parent-cal__pending">수업</span>
              ) : null}
            </div>
          );
        })}
      </div>

      <div className="parent-legend">
        <StatusBadge status="출석" />
        <StatusBadge status="지각" />
        <StatusBadge status="결석" />
      </div>
    </Card>
  );
}

/** 달력 한 판 — 앞뒤 빈칸을 포함한 7의 배수 셀. */
function monthCells(month: string): (string | null)[] {
  const [year, monthNo] = month.split("-").map(Number);
  const firstWeekday = new Date(year, monthNo - 1, 1).getDay();
  const dayCount = new Date(year, monthNo, 0).getDate();
  const cells: (string | null)[] = Array(firstWeekday).fill(null);
  for (let day = 1; day <= dayCount; day += 1) {
    cells.push(`${month}-${String(day).padStart(2, "0")}`);
  }
  while (cells.length % 7 !== 0) cells.push(null);
  return cells;
}

/* ── 결석·동보 ──────────────────────────────────────────────────── */

function AbsenceCard({ rows }: { rows: AbsenceRow[] }) {
  return (
    <Card
      title="결석과 보강 영상"
      padding="none"
      actions={rows.length > 0 ? <Link to="/parent/makeup">보강 영상 신청 화면</Link> : undefined}
    >
      {rows.length === 0 ? (
        <EmptyState title="이번 달 결석이 없습니다" />
      ) : (
        <Table
          rows={rows}
          rowKey={(row) => row.date}
          caption="이번 달 결석일과 보강 영상 신청 상태"
          columns={[
            {
              key: "date",
              header: "결석한 날",
              cell: (row) => dayLabel(row.date),
            },
            {
              key: "makeup",
              header: "보강 영상",
              cell: (row) =>
                row.makeup_status ? (
                  <StatusBadge status={row.makeup_status} />
                ) : (
                  <Badge tone="outline">신청 전</Badge>
                ),
            },
          ]}
        />
      )}
    </Card>
  );
}

/* ── 마감 임박 ──────────────────────────────────────────────────── */

interface DeadlineItem {
  key: string;
  kind: string;
  title: string;
  detail: string;
  dueDate: string | null;
  dDay: number | null;
}

/** 같은 주차 영상 만료가 여러 건이면 한 줄로 묶는다(줄 수만 줄이고 값은 그대로). */
function summarize(rows: Deadline[]): DeadlineItem[] {
  const videos = new Map<string, DeadlineItem & { count: number }>();
  const items: DeadlineItem[] = [];

  for (const row of rows) {
    if (row.kind === "영상만료") {
      const video = row as VideoDeadline;
      const key = `video-${video.course_name}-${video.week_no}-${video.due_date}`;
      const found = videos.get(key);
      if (found) {
        found.count += 1;
        found.detail = `${found.count}건 시청 기한`;
        continue;
      }
      videos.set(key, {
        key,
        kind: "보강 영상",
        title: `${video.course_name} ${video.week_no}주차 영상`,
        detail: "1건 시청 기한",
        dueDate: video.due_date,
        dDay: video.d_day,
        count: 1,
      });
      continue;
    }
    if (row.kind === "클리닉") {
      const clinic = row as ClinicDeadline;
      items.push({
        key: `clinic-${clinic.clinic_id}`,
        kind: "클리닉",
        title: `${shortDay(clinic.date)} ${clinic.start_time} 클리닉`,
        detail: clinic.link_active
          ? "참여 링크가 열려 있습니다"
          : "참여 링크는 시작 5분 전에 열립니다",
        dueDate: clinic.due_date,
        dDay: clinic.d_day,
      });
      continue;
    }
    if (row.kind === "교재결제") {
      const order = row as PaymentDeadline;
      items.push({
        key: `order-${order.order_id}`,
        kind: "교재 결제",
        title: order.product_name,
        detail: `${money(order.amount)} 미결제`,
        dueDate: order.due_date,
        dDay: order.d_day,
      });
      continue;
    }
    items.push({
      key: `${row.kind}-${row.due_date ?? "none"}`,
      kind: row.kind,
      title: row.kind,
      detail: "",
      dueDate: row.due_date,
      dDay: row.d_day,
    });
  }

  return [...items, ...videos.values()].sort((left, right) => {
    if (left.dueDate === right.dueDate) return left.title.localeCompare(right.title, "ko");
    if (left.dueDate === null) return 1;
    if (right.dueDate === null) return -1;
    return left.dueDate < right.dueDate ? -1 : 1;
  });
}

function DeadlineCard({ rows }: { rows: Deadline[] }) {
  const items = summarize(rows);
  return (
    <Card title="곧 마감되는 것" padding="none">
      {items.length === 0 ? (
        <EmptyState title="기한이 다가온 항목이 없습니다" />
      ) : (
        <Table
          rows={items}
          rowKey={(row) => row.key}
          caption="기한이 다가온 항목"
          columns={[
            {
              key: "kind",
              header: "종류",
              width: "7rem",
              cell: (row) => <Badge tone="neutral">{row.kind}</Badge>,
            },
            {
              key: "title",
              header: "항목",
              cell: (row) => (
                <>
                  <div>{row.title}</div>
                  {row.detail && <div className="parent-note">{row.detail}</div>}
                </>
              ),
            },
            {
              key: "due",
              header: "기한",
              width: "10rem",
              cell: (row) => (
                // 날짜는 .num(모노) 을 씌우지 않는다 — "8월 4일"의 공백까지 모노 폭이
                // 되어 월과 일 사이가 벌어진다. 다른 화면의 날짜 칸과도 같은 서체다.
                <>
                  <div>{row.dueDate ? shortDay(row.dueDate) : "—"}</div>
                  <div className="parent-note">{dDayLabel(row.dDay)}</div>
                </>
              ),
            },
          ]}
        />
      )}
    </Card>
  );
}

/* ── 교재 결제 ──────────────────────────────────────────────────── */

function PaymentCard({ rows }: { rows: PaymentRow[] }) {
  return (
    <Card title="교재 결제" padding="none">
      {rows.length === 0 ? (
        <EmptyState title="청구된 교재가 없습니다" />
      ) : (
        <Table
          rows={rows}
          rowKey={(row) => row.order_id}
          caption="교재 청구·결제 상태"
          columns={[
            { key: "name", header: "교재", cell: (row) => row.product_name },
            {
              key: "amount",
              header: "금액",
              align: "right",
              numeric: true,
              cell: (row) => money(row.amount),
            },
            {
              key: "status",
              header: "결제",
              cell: (row) =>
                row.status === "결제완료" ? (
                  <Badge tone="success">결제완료</Badge>
                ) : (
                  <Badge tone="warning">{row.status}</Badge>
                ),
            },
            {
              key: "billed",
              header: "청구서",
              cell: (row) => (row.is_billed ? "발송함" : "발송 전"),
            },
          ]}
        />
      )}
    </Card>
  );
}

/* ── 주차별 수업 계획 ───────────────────────────────────────────── */

function WeekCard({ weeks }: { weeks: HomeWeek[] }) {
  const open = weeks.filter((week) => !week.locked);

  return (
    <Card title="주차별 수업 계획" aside={`공개된 ${open.length}주차`}>
      <div className="ui-stack ui-stack--sm">
        {open.map((week) => (
            <DetailsPanel
              key={week.week_no}
              summary={withPrefix(`${week.week_no}주차`, week.title)}
              aside={
                week.start_date && week.end_date
                  ? `${shortDay(week.start_date)} ~ ${shortDay(week.end_date)}`
                  : undefined
              }
            >
              {week.offline_notice && (
                <p className="parent-note parent-note--lead">학원 공지 — {week.offline_notice}</p>
              )}
              {(week.day_plans ?? []).length === 0 ? (
                <p className="parent-note">학습 계획이 아직 없습니다</p>
              ) : (
                <ul className="parent-plans">
                  {(week.day_plans ?? []).map((plan) => (
                    <li key={plan.day_no}>
                      <strong className="parent-plans__title">
                        {withPrefix(`Day ${plan.day_no}`, plan.title)}
                      </strong>
                      <span className="parent-note">{plan.content}</span>
                    </li>
                  ))}
                </ul>
              )}
            </DetailsPanel>
        ))}
      </div>
    </Card>
  );
}

/* ── 등록 전 자녀 ───────────────────────────────────────────────── */

function NotEnrolled({ data }: { data: ParentHome }) {
  const products = data.purchasable_products ?? [];
  return (
    <>
      {/* 이름·등록 상태는 바로 위 카드가 이미 들고 있다 — 여기서는 달력이 없는
          이유만 한 줄로 말한다. */}
      <Card padding="none">
        <EmptyState title="아직 수업이 시작되지 않았습니다" />
      </Card>
      <Card title="구매할 수 있는 교재" padding="none">
        {products.length === 0 ? (
          <EmptyState title="지금 구매할 수 있는 교재가 없습니다" />
        ) : (
          <Table
            rows={products}
            rowKey={(row) => row.product_id}
            caption="구매 가능 교재"
            columns={[
              { key: "name", header: "교재", cell: (row) => row.name },
              {
                key: "price",
                header: "가격",
                align: "right",
                numeric: true,
                cell: (row) => money(row.price),
              },
            ]}
          />
        )}
      </Card>
      {data.payment_status && <PaymentCard rows={data.payment_status} />}
    </>
  );
}

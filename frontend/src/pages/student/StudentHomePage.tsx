/**
 * 학생 홈 — 캘린더 · 마감 · 주차별 커리큘럼 (PRD 3.2.0)
 * GET /api/student/home?month=YYYY-MM
 *
 * 상태 기반 노출(PRD §4):
 *  - 예비등록 학생에게는 calendar·course·deadlines 가 아예 내려오지 않는다.
 *    → 교재 구매 안내만 있는 홈을 그린다(성적·클리닉 UI 를 상상해 만들지 않는다).
 *  - 잠긴 주차(locked)는 week_no 외에 아무것도 오지 않는다 → "공개 예정"만.
 */
import { useMemo, useState } from "react";

import { http, useApi } from "../../api";
import {
  Badge,
  Button,
  Card,
  DetailsPanel,
  EmptyState,
  ErrorState,
  Loading,
  PageHeader,
  Table,
} from "../../components";
import {
  CalendarDay,
  Deadline,
  OpenWeek,
  StudentHome,
  currentMonth,
  dateTimeLabel,
  dayLabel,
  ddayLabel,
  monthGrid,
  monthLabel,
  shiftMonth,
  weekdayName,
  won,
} from "./lib";
import "./student.css";

/** 같은 주차·같은 만료일의 복습영상 권한은 한 줄로 묶는다(내용 동일 — 건수만 표시). */
interface DueItem {
  key: string;
  dDay: number | null;
  title: string;
  meta: string;
  count: number;
}

function toDueItems(deadlines: Deadline[]): DueItem[] {
  const items: DueItem[] = [];
  const videoIndex = new Map<string, number>();

  for (const row of deadlines) {
    if (row.kind === "클리닉") {
      items.push({
        key: `clinic-${row.clinic_id}`,
        dDay: row.d_day,
        count: 1,
        title: `클리닉 ${dayLabel(row.date)} ${row.start_time}`,
        meta: row.link_active
          ? "지금 입장할 수 있습니다 — 클리닉 신청 화면에서 링크를 여세요."
          : "미트 링크는 시작 5분 전에 열립니다.",
      });
    } else if (row.kind === "영상만료") {
      const key = `video-${row.course_name}-${row.week_no}-${row.due_date ?? ""}`;
      const found = videoIndex.get(key);
      if (found !== undefined) {
        items[found].count += 1;
        items[found].meta = `${dateTimeLabel(row.expires_at)}까지 · 영상 ${items[found].count}개`;
        continue;
      }
      videoIndex.set(key, items.length);
      items.push({
        key,
        dDay: row.d_day,
        count: 1,
        title: `${row.course_name} ${row.week_no}주차 복습영상`,
        meta: `${dateTimeLabel(row.expires_at)}까지 볼 수 있습니다.`,
      });
    } else {
      items.push({
        key: `order-${row.order_id}`,
        dDay: row.d_day,
        count: 1,
        title: `${row.product_name} 결제 전`,
        meta: `${won(row.amount)} · 결제가 확인되면 자동으로 사라집니다.`,
      });
    }
  }

  return items.sort((a, b) => {
    if (a.dDay === null) return b.dDay === null ? 0 : 1;
    if (b.dDay === null) return -1;
    return a.dDay - b.dDay;
  });
}

const DOW = ["일", "월", "화", "수", "목", "금", "토"];

export default function StudentHomePage() {
  const [month, setMonth] = useState(currentMonth());
  const home = useApi(
    () => http.get<StudentHome>("/student/home", { params: { month } }).then((r) => r.data),
    [month],
  );

  const data = home.data;
  const dayMap = useMemo(() => {
    const map = new Map<string, CalendarDay>();
    for (const day of data?.calendar?.days ?? []) map.set(day.date, day);
    return map;
  }, [data]);
  const dues = useMemo(() => toDueItems(data?.deadlines ?? []), [data]);

  if (home.loading) {
    return (
      <>
        <PageHeader title="홈" />
        <Loading label="이번 달 일정을 불러오는 중…" />
      </>
    );
  }

  if (home.error || !data) {
    return (
      <>
        <PageHeader title="홈" />
        <ErrorState description={home.error ?? undefined} onRetry={home.reload} />
      </>
    );
  }

  const { student, course, calendar } = data;

  /* ── 예비등록 · 퇴원: 서버가 캘린더를 주지 않는다 ─────────────────── */
  if (!calendar) {
    const products = data.purchasable_products ?? [];
    return (
      <>
        <PageHeader
          title={`${student.name} 학생, 반갑습니다`}
          description="아직 수강 등록 전이라 학습 화면은 열려 있지 않습니다. 교재를 구매하고 반이 확정되면 캘린더와 성적이 이곳에 채워집니다."
        />
        <div className="ui-stack">
          <Card title="지금 상태">
            <div className="ui-row">
              <Badge tone="warning">{student.enrollment_status}</Badge>
              {student.current_class && <Badge tone="outline">{student.current_class} 예정</Badge>}
            </div>
            <p className="st-note" style={{ marginTop: "var(--space-sm)" }}>
              등록이 확정되면 출결 캘린더 · 주차별 학습계획 · 성적표가 자동으로 열립니다. 절차가
              궁금하면 학원으로 문의해 주세요.
            </p>
          </Card>

          <Card title="구매 가능한 교재" aside={`${products.length}종`} padding="none">
            <Table
              rows={products}
              rowKey={(row) => row.product_id}
              caption="구매 가능한 교재 목록"
              empty="지금 구매할 수 있는 교재가 없습니다. 등록 안내를 기다려 주세요."
              columns={[
                { key: "name", header: "교재", cell: (row) => row.name },
                {
                  key: "price",
                  header: "가격",
                  align: "right",
                  numeric: true,
                  cell: (row) => won(row.price),
                },
              ]}
            />
          </Card>
        </div>
      </>
    );
  }

  /* ── 등록 학생: 캘린더 홈 ─────────────────────────────────────────── */
  const weeks = calendar.weeks;
  const lockedCount = weeks.filter((w) => w.locked).length;
  const totalWeeks = course?.total_weeks ?? weeks.length;
  const currentWeek = course?.current_week ?? null;
  const progress = totalWeeks > 0 ? Math.min(100, ((currentWeek ?? 0) / totalWeeks) * 100) : 0;
  const classDays = (course?.class_weekdays ?? []).map(weekdayName).join("·");

  const description = course
    ? `${course.name} · ${student.current_class ?? "반 미배정"} — 수업은 매주 ${classDays}요일입니다.`
    : "이번 달 출결과 앞으로 해야 할 일입니다.";

  return (
    <>
      <PageHeader
        title={`${student.name} 학생의 학습 현황`}
        description={description}
        actions={
          currentWeek !== null ? (
            <Badge tone="accent">
              {totalWeeks}주 과정 중 {currentWeek}주차
            </Badge>
          ) : undefined
        }
      />

      <div className="ui-stack">
        <Card
          title="오늘 놓치면 안 되는 것"
          aside={dues.length > 0 ? "기한이 가까운 순" : undefined}
        >
          {dues.length === 0 ? (
            <EmptyState
              title="지금 급한 일은 없습니다"
              description="클리닉 예약, 복습영상 만료, 교재 결제가 생기면 여기에서 먼저 알려드립니다."
            />
          ) : (
            <ul className="st-due">
              {dues.map((item) => (
                <li
                  key={item.key}
                  className={[
                    "st-due__item",
                    item.dDay !== null && item.dDay <= 1 ? "st-due__item--soon" : "",
                  ]
                    .filter(Boolean)
                    .join(" ")}
                >
                  <span
                    className={[
                      "st-due__dday",
                      item.dDay === null ? "st-due__dday--none" : "",
                    ]
                      .filter(Boolean)
                      .join(" ")}
                  >
                    {ddayLabel(item.dDay)}
                  </span>
                  <span className="st-due__body">
                    <span className="st-due__title">{item.title}</span>
                    <span className="st-due__meta">{item.meta}</span>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <div className="st-split">
          <Card
            title={monthLabel(month)}
            aside="출결"
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
            <div className="st-cal">
              {DOW.map((name) => (
                <div key={name} className="st-cal__dow">
                  {name}
                </div>
              ))}
              {monthGrid(month)
                .flat()
                .map((date, index) => {
                  if (!date) return <div key={`b-${index}`} className="st-cal__blank" />;
                  const info = dayMap.get(date);
                  const isToday = date === data.today;
                  const mark = info?.attendance ?? (info?.has_class_session ? "예정" : null);
                  return (
                    <div
                      key={date}
                      className={[
                        "st-cal__cell",
                        info?.has_class_session ? "st-cal__cell--class" : "",
                        isToday ? "st-cal__cell--today" : "",
                      ]
                        .filter(Boolean)
                        .join(" ")}
                    >
                      <span className="st-cal__day">
                        {Number(date.slice(8))}
                        {isToday && <span className="st-cal__today">오늘</span>}
                      </span>
                      {mark && (
                        <span className={`st-cal__mark st-cal__mark--${mark}`}>
                          {mark === "예정" ? "수업" : mark}
                        </span>
                      )}
                    </div>
                  );
                })}
            </div>
            <p className="st-note" style={{ marginTop: "var(--space-md)" }}>
              색이 들어간 날은 출결이 확정된 수업일입니다. 회색 "수업"은 아직 출결이 입력되지
              않은 수업일이고, 결석한 날은 동보 신청으로 복습영상을 받을 수 있습니다.
            </p>
          </Card>

          <Card title="주차별 학습계획" aside={course?.name}>
            {currentWeek !== null && (
              <div className="st-progress">
                <span className="st-progress__track">
                  <span className="st-progress__fill" style={{ width: `${progress}%` }} />
                </span>
                <span className="st-progress__label num">
                  {currentWeek} / {totalWeeks}주차
                </span>
              </div>
            )}

            <div className="st-weeks">
              {weeks.map((week) =>
                week.locked ? (
                  <p key={week.week_no} className="st-week-locked">
                    <span>{week.week_no}주차</span>
                    <span>공개 예정</span>
                  </p>
                ) : (
                  <WeekPanel key={week.week_no} week={week} open={week.week_no === currentWeek} />
                ),
              )}
            </div>

            {lockedCount > 0 && (
              <p className="st-note" style={{ marginTop: "var(--space-md)" }}>
                남은 {lockedCount}개 주차는 진도에 맞춰 차례로 열립니다.
              </p>
            )}
          </Card>
        </div>
      </div>
    </>
  );
}

function WeekPanel({ week, open }: { week: OpenWeek; open: boolean }) {
  const period = `${week.start_date.slice(5).replace("-", ".")}~${week.end_date
    .slice(5)
    .replace("-", ".")}`;
  return (
    <DetailsPanel
      defaultOpen={open}
      summary={week.label || `${week.week_no}주차`}
      aside={period}
    >
      <p className="st-day__title" style={{ marginBottom: "var(--space-sm)" }}>
        {week.title}
      </p>
      {week.offline_notice && (
        <p className="st-note" style={{ marginBottom: "var(--space-md)" }}>
          주차 공지 — {week.offline_notice}
        </p>
      )}
      <div className="st-daylist">
        {week.day_plans.length === 0 ? (
          <p className="st-note">이 주차의 Day 학습계획은 아직 올라오지 않았습니다.</p>
        ) : (
          week.day_plans.map((plan) => (
            <div key={plan.day_no} className="st-day">
              <span className="st-day__no">Day {plan.day_no}</span>
              <span className="st-day__title">{plan.title}</span>
              <span className="st-day__content">{plan.content}</span>
            </div>
          ))
        )}
      </div>
    </DetailsPanel>
  );
}

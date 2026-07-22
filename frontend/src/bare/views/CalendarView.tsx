/**
 * 캘린더 홈 공용 뷰 — 학생·학부모 동일 화면(PRD 3.2.0).
 * 실제 월 그리드로 출결 도장·수업일을 표시하고, 주차(잠금 게이팅)·마감 목록,
 * 학부모 블록(결제 상태·결석/동보)을 표로 렌더한다.
 */
import { Link } from "react-router-dom";

import { WEEKDAYS, weekdayName } from "../ui";

// 홈 페이로드는 서버 조립 JSON 그대로 — bare 렌더 목적상 any 로 다룬다.
/* eslint-disable @typescript-eslint/no-explicit-any */

export function shiftMonth(month: string, delta: number): string {
  const [year, monthNo] = month.split("-").map(Number);
  const date = new Date(year, monthNo - 1 + delta, 1);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
}

function monthGrid(month: string): (string | null)[][] {
  const [year, monthNo] = month.split("-").map(Number);
  const first = new Date(year, monthNo - 1, 1);
  const daysInMonth = new Date(year, monthNo, 0).getDate();
  const cells: (string | null)[] = Array(first.getDay()).fill(null);
  for (let day = 1; day <= daysInMonth; day += 1) {
    cells.push(`${month}-${String(day).padStart(2, "0")}`);
  }
  while (cells.length % 7 !== 0) cells.push(null);
  const rows: (string | null)[][] = [];
  for (let i = 0; i < cells.length; i += 7) rows.push(cells.slice(i, i + 7));
  return rows;
}

export default function CalendarView({
  data,
  month,
  onMonth,
  makeupPath,
}: {
  data: any;
  month: string;
  onMonth: (next: string) => void;
  makeupPath?: string;
}) {
  const student = data.student;
  // 미등록(예비등록)·퇴원 — bare 페이로드(구매 가능 교재만, PRD §4)
  if (!data.calendar) {
    return (
      <div>
        <p>
          <strong>{student?.name}</strong> — 등록 상태: {student?.enrollment_status}
        </p>
        <p className="muted">
          미등록(예비등록) 상태는 캘린더 없이 교재 구매만 가능한 bare 홈이 내려온다(상태 기반
          노출).
        </p>
        <h3>구매 가능 교재</h3>
        <table>
          <thead>
            <tr>
              <th>교재</th>
              <th>가격</th>
            </tr>
          </thead>
          <tbody>
            {(data.purchasable_products ?? []).map((product: any) => (
              <tr key={product.product_id}>
                <td>{product.name}</td>
                <td>{product.price.toLocaleString()}원</td>
              </tr>
            ))}
          </tbody>
        </table>
        {data.payment_status && <PaymentTable rows={data.payment_status} />}
      </div>
    );
  }

  const dayMap: Record<string, any> = {};
  for (const day of data.calendar.days ?? []) dayMap[day.date] = day;
  const course = data.course;

  return (
    <div>
      <p>
        <strong>{student.name}</strong>
        {student.current_class ? ` · ${student.current_class}` : ""} · {student.enrollment_status}
        {course && (
          <>
            {" — "}
            {course.name}
            {course.class_name ? `(${course.class_name})` : ""} · 진행{" "}
            {course.current_week ?? "-"}/{course.total_weeks}주차 · 수업 요일:{" "}
            {(course.class_weekdays ?? []).map((w: number) => weekdayName(w)).join("·")}
          </>
        )}
      </p>

      <p className="inline">
        <button onClick={() => onMonth(shiftMonth(month, -1))}>이전 달</button>
        <strong> {data.month} </strong>
        <button onClick={() => onMonth(shiftMonth(month, 1))}>다음 달</button>
      </p>
      <table className="cal">
        <thead>
          <tr>
            {WEEKDAYS.map((name) => (
              <th key={name}>{name}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {monthGrid(month).map((row, rowIndex) => (
            <tr key={rowIndex}>
              {row.map((date, cellIndex) => {
                if (!date) return <td key={cellIndex} />;
                const info = dayMap[date];
                const isToday = date === data.today;
                return (
                  <td key={cellIndex} className={isToday ? "today" : undefined}>
                    <div>{Number(date.slice(8))}{isToday ? " (오늘)" : ""}</div>
                    {info?.has_class_session && <div className="muted">수업</div>}
                    {info?.attendance && <div><strong>[{info.attendance}]</strong></div>}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>

      <h3>마감 임박</h3>
      {data.deadlines.length === 0 ? (
        <p className="muted">마감 임박 항목 없음</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>종류</th>
              <th>기한</th>
              <th>D-day</th>
              <th>내용</th>
            </tr>
          </thead>
          <tbody>
            {data.deadlines.map((item: any, index: number) => (
              <tr key={index}>
                <td>{item.kind}</td>
                <td>{item.due_date ?? "-"}</td>
                <td>{item.d_day === null || item.d_day === undefined ? "-" : `D-${item.d_day}`}</td>
                <td>
                  {item.kind === "클리닉" &&
                    `${item.date} ${item.start_time} 시작 — 링크 ${item.link_active ? "활성" : "비활성(시작 5분 전 공개)"}`}
                  {item.kind === "영상만료" &&
                    `${item.course_name} ${item.week_no}주차 — ${item.expires_at} 만료`}
                  {item.kind === "교재결제" &&
                    `${item.product_name} ${item.amount.toLocaleString()}원 미결제`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h3>주차별 커리큘럼 (미래 주차는 잠금 — 상태 기반 노출)</h3>
      <table>
        <thead>
          <tr>
            <th>주차</th>
            <th>기간</th>
            <th>제목</th>
            <th>주차 공지</th>
            <th>Day 학습계획</th>
          </tr>
        </thead>
        <tbody>
          {data.calendar.weeks.map((week: any) => (
            <tr key={week.week_no}>
              <td>{week.week_no}주차</td>
              {week.locked ? (
                <td colSpan={4} className="muted">
                  잠김 — 미공개(제목·날짜·계획 미노출)
                </td>
              ) : (
                <>
                  <td>
                    {week.start_date} ~ {week.end_date}
                  </td>
                  <td>{week.title}</td>
                  <td>{week.offline_notice ?? "-"}</td>
                  <td>
                    <details>
                      <summary>Day {week.day_plans.length}건</summary>
                      <ul>
                        {week.day_plans.map((plan: any) => (
                          <li key={plan.day_no}>
                            Day{plan.day_no} {plan.title}: {plan.content}
                          </li>
                        ))}
                      </ul>
                    </details>
                  </td>
                </>
              )}
            </tr>
          ))}
        </tbody>
      </table>

      {data.payment_status && (
        <>
          <h3>교재 결제 상태 (학부모 블록)</h3>
          <PaymentTable rows={data.payment_status} />
        </>
      )}
      {data.absences && (
        <>
          <h3>이달 결석·동보 (학부모 블록)</h3>
          <table>
            <thead>
              <tr>
                <th>결석일</th>
                <th>동보 상태</th>
              </tr>
            </thead>
            <tbody>
              {data.absences.length === 0 && (
                <tr>
                  <td colSpan={2} className="muted">
                    이달 결석 없음
                  </td>
                </tr>
              )}
              {data.absences.map((absence: any, index: number) => (
                <tr key={index}>
                  <td>{absence.date}</td>
                  <td>{absence.makeup_status ?? "미신청"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {makeupPath && (
            <p>
              <Link to={makeupPath}>동보 신청 화면으로 이동</Link>
            </p>
          )}
        </>
      )}
    </div>
  );
}

function PaymentTable({ rows }: { rows: any[] }) {
  return (
    <table>
      <thead>
        <tr>
          <th>교재</th>
          <th>금액</th>
          <th>상태</th>
          <th>청구서 발송</th>
          <th>결제 시각</th>
        </tr>
      </thead>
      <tbody>
        {rows.length === 0 && (
          <tr>
            <td colSpan={5} className="muted">
              주문 없음
            </td>
          </tr>
        )}
        {rows.map((row) => (
          <tr key={row.order_id}>
            <td>{row.product_name}</td>
            <td>{row.amount.toLocaleString()}원</td>
            <td>{row.status}</td>
            <td>{row.is_billed ? `발송(${row.billed_at ?? "-"})` : "미발송"}</td>
            <td>{row.paid_at ?? "-"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** 클리닉 신청 — 자격 게이팅·슬롯 잔여·신청/변경/취소 (PRD 3.2.4). */
/* eslint-disable @typescript-eslint/no-explicit-any */
import { useState } from "react";

import { api, errMsg } from "../../api";
import { Msg, useLoad, weekdayName } from "../../ui";

export default function StudentClinicPage() {
  const [examId, setExamId] = useState<number | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [changeSlot, setChangeSlot] = useState<Record<number, number>>({});

  const grades = useLoad<any>(async () => (await api.get("/student/grades")).data, []);
  const exams: any[] = grades.data?.exams ?? [];
  const effectiveExamId = examId ?? (exams.length > 0 ? exams[exams.length - 1].exam_id : null);

  const clinic = useLoad<any>(
    async () =>
      effectiveExamId === null
        ? null
        : (await api.get("/student/clinic", { params: { exam_id: effectiveExamId } })).data,
    [effectiveExamId],
  );

  const act = async (fn: () => Promise<unknown>, okMessage: string) => {
    setMessage(null);
    setError(null);
    try {
      await fn();
      setMessage(okMessage);
      await clinic.reload();
    } catch (e) {
      setError(errMsg(e));
    }
  };

  const request = (slot: any) =>
    act(
      () =>
        api.post("/student/clinic/requests", {
          exam_id: effectiveExamId,
          slot_id: slot.slot_id,
          requested_date: slot.next_date,
        }),
      "신청 완료(대기 상태) — 관리자 승인·배정을 기다립니다.",
    );

  const change = (row: any) => {
    const slotId = changeSlot[row.clinic_id];
    const slot = (clinic.data?.slots ?? []).find((s: any) => s.slot_id === slotId);
    if (!slot) {
      setError("변경할 슬롯을 선택하세요.");
      return;
    }
    return act(
      () =>
        api.patch(`/student/clinic/requests/${row.clinic_id}`, {
          slot_id: slot.slot_id,
          requested_date: slot.next_date,
        }),
      "변경 완료 — 승인배정이었다면 대기 상태로 되돌아갑니다(재승인 대상).",
    );
  };

  const cancel = (row: any) =>
    act(
      () => api.post(`/student/clinic/requests/${row.clinic_id}/cancel`),
      "취소 완료(노쇼로 집계되지 않음).",
    );

  const data = clinic.data;
  return (
    <section>
      <h2>클리닉 신청</h2>
      <p className="inline">
        대상 시험:{" "}
        <select
          value={effectiveExamId ?? ""}
          onChange={(e) => setExamId(Number(e.target.value))}
        >
          {exams.map((exam: any) => (
            <option key={exam.exam_id} value={exam.exam_id}>
              {exam.name} ({exam.exam_date})
            </option>
          ))}
        </select>
      </p>
      <Msg error={error ?? clinic.error ?? grades.error} ok={message} />
      {clinic.loading && <p>불러오는 중…</p>}
      {data && (
        <>
          <p>
            자격:{" "}
            {data.eligibility.is_target ? (
              <strong className="ok">대상자 — 신청 가능</strong>
            ) : (
              <strong className="error">
                미대상자{data.eligibility.reason ? ` (사유: ${data.eligibility.reason})` : ""}
              </strong>
            )}
            {data.clinic_banned && (
              <strong className="error"> · 노쇼 누적으로 신청 제한된 계정</strong>
            )}
          </p>

          {data.slots ? (
            <>
              <h3>신청 가능 슬롯 (월~금, 다음 신청 가능일 기준)</h3>
              <table>
                <thead>
                  <tr>
                    <th>요일</th>
                    <th>시간</th>
                    <th>신청일</th>
                    <th>잔여/정원</th>
                    <th>신청</th>
                  </tr>
                </thead>
                <tbody>
                  {data.slots.map((slot: any) => (
                    <tr key={slot.slot_id}>
                      <td>{weekdayName(slot.weekday)}</td>
                      <td>
                        {slot.start_time}~{slot.end_time}
                      </td>
                      <td>{slot.next_date}</td>
                      <td>
                        {slot.remaining}/{slot.capacity}
                      </td>
                      <td>
                        <button disabled={slot.is_full} onClick={() => request(slot)}>
                          {slot.is_full ? "마감" : "신청"}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          ) : (
            <p className="muted">
              슬롯 목록이 내려오지 않음 — 대상자가 아니면 신청 가능한 시간대 자체가 없다(상태
              기반 노출).
            </p>
          )}

          <h3>내 신청 현황</h3>
          <table>
            <thead>
              <tr>
                <th>번호</th>
                <th>날짜</th>
                <th>시간</th>
                <th>상태</th>
                <th>미트 링크</th>
                <th>변경/취소</th>
              </tr>
            </thead>
            <tbody>
              {data.my_requests.length === 0 && (
                <tr>
                  <td colSpan={6} className="muted">
                    신청 없음
                  </td>
                </tr>
              )}
              {data.my_requests.map((row: any) => (
                <tr key={row.clinic_id}>
                  <td>{row.clinic_id}</td>
                  <td>{row.requested_date}</td>
                  <td>{row.requested_time}</td>
                  <td>{row.status}</td>
                  <td>
                    {row.meet_url ? (
                      <a href={row.meet_url} target="_blank" rel="noreferrer">
                        입장
                      </a>
                    ) : row.status === "승인배정" ? (
                      "시작 5분 전 공개"
                    ) : (
                      "-"
                    )}
                  </td>
                  <td className="inline">
                    {(row.status === "대기" || row.status === "승인배정") && (
                      <>
                        <select
                          value={changeSlot[row.clinic_id] ?? ""}
                          onChange={(e) =>
                            setChangeSlot({
                              ...changeSlot,
                              [row.clinic_id]: Number(e.target.value),
                            })
                          }
                        >
                          <option value="">슬롯 선택</option>
                          {(data.slots ?? []).map((slot: any) => (
                            <option key={slot.slot_id} value={slot.slot_id}>
                              {weekdayName(slot.weekday)} {slot.start_time} ({slot.next_date})
                            </option>
                          ))}
                        </select>
                        <button onClick={() => change(row)}>변경</button>
                        <button onClick={() => cancel(row)}>취소</button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted">
            당일 오전 8시 이후에는 그 날짜의 신청·변경·취소가 400으로 막힌다 — 눌러서 확인
            가능.
          </p>
        </>
      )}
    </section>
  );
}

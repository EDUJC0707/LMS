/** 결석 상담 대기열 — 통화 결과 기록(3회 미연결 시 문자 종결) (PRD 3.1.9). */
/* eslint-disable @typescript-eslint/no-explicit-any */
import { FormEvent, useState } from "react";

import { api, errMsg } from "../../api";
import { Msg, useLoad } from "../../ui";

export default function CounselingPage() {
  const [selected, setSelected] = useState<any>(null);
  const queue = useLoad<any>(
    async () => (await api.get("/admin/counseling/queue")).data,
    [],
  );
  return (
    <section>
      <h2>결석 상담 대기열</h2>
      <p className="muted">
        출결에서 결석 저장 시 자동 생성된 카드(1차 통화 대상=학부모). 미연결 기록은 재시도
        카드를 만들고, 3회째 미연결이면 알림톡 종결 기록이 남는다.
      </p>
      <Msg error={queue.error} />
      {queue.data && (
        <table>
          <thead>
            <tr>
              <th>카드</th>
              <th>학생</th>
              <th>결석일</th>
              <th>통화 대상</th>
              <th>시도 횟수</th>
              <th>생성 시각</th>
              <th>기록</th>
            </tr>
          </thead>
          <tbody>
            {queue.data.queue.length === 0 && (
              <tr>
                <td colSpan={7} className="muted">
                  대기 중 카드 없음
                </td>
              </tr>
            )}
            {queue.data.queue.map((card: any) => (
              <tr key={card.counsel_id}>
                <td>{card.counsel_id}</td>
                <td>
                  {card.student.name} (원번 {card.student.matching_key})
                </td>
                <td>{card.absence_date ?? "-"}</td>
                <td>{card.target}</td>
                <td>{card.attempts}회</td>
                <td>{card.created_at}</td>
                <td>
                  <button onClick={() => setSelected(card)}>통화 결과 기록</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {selected && (
        <RecordForm
          card={selected}
          onDone={() => {
            setSelected(null);
            void queue.reload();
          }}
        />
      )}
    </section>
  );
}

function RecordForm({ card, onDone }: { card: any; onDone: () => void }) {
  const [result, setResult] = useState("연결");
  const [reason, setReason] = useState("");
  const [memo, setMemo] = useState("");
  const [followUp, setFollowUp] = useState("");
  const [makeupRequested, setMakeupRequested] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    try {
      const { data } = await api.patch(`/admin/counseling/${card.counsel_id}`, {
        result,
        absence_reason: reason,
        call_memo: memo,
        follow_up_action: followUp,
        makeup_requested: makeupRequested,
      });
      setOk(
        `기록 완료 — 상태 ${data.status} · 시도 ${data.attempts}회` +
          (data.next_counsel_id ? ` · 재시도 카드 #${data.next_counsel_id} 생성` : "") +
          (data.closed ? " · 종결 — 알림톡은 버튼으로" : "") +
          (data.makeup_requested
            ? " · 동보 희망 체크됨(지급은 출결 화면의 동보 체크 API로)"
            : ""),
      );
    } catch (e) {
      setError(errMsg(e));
    }
  };

  return (
    <fieldset>
      <legend>
        카드 #{card.counsel_id} — {card.student.name} ({card.target} 통화)
      </legend>
      <form onSubmit={submit}>
        <p className="inline">
          결과:{" "}
          <select value={result} onChange={(e) => setResult(e.target.value)}>
            <option value="연결">연결(완료)</option>
            <option value="미연결">미연결(재시도/종결)</option>
          </select>
          <label>
            <input
              type="checkbox"
              checked={makeupRequested}
              onChange={(e) => setMakeupRequested(e.target.checked)}
            />{" "}
            동보 신청 희망
          </label>
        </p>
        <p>
          <input
            placeholder="결석 사유"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            size={40}
          />
        </p>
        <p>
          <textarea
            placeholder="통화 내용 메모"
            rows={3}
            value={memo}
            onChange={(e) => setMemo(e.target.value)}
          />
        </p>
        <p>
          <input
            placeholder="후속 조치"
            value={followUp}
            onChange={(e) => setFollowUp(e.target.value)}
            size={40}
          />
        </p>
        <button type="submit">기록 저장</button> <button onClick={onDone}>닫기</button>
      </form>
      <Msg error={error} ok={ok} />
    </fieldset>
  );
}

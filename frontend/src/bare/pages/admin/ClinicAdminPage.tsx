/** 클리닉 관리 — 대기열·승인배정·출결(노쇼)·평가·unban·평가 항목 (PRD 3.2.4). */
/* eslint-disable @typescript-eslint/no-explicit-any */
import { useState } from "react";

import { useMe } from "../../MeContext";
import { api, errMsg } from "../../api";
import { Msg, useLoad } from "../../ui";

export default function ClinicAdminPage() {
  const { me } = useMe();
  const [statusFilter, setStatusFilter] = useState("");
  const [dateFilter, setDateFilter] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);
  const [evalTarget, setEvalTarget] = useState<number | null>(null);

  const queue = useLoad<any>(
    async () =>
      (
        await api.get("/admin/clinic/requests", {
          params: {
            ...(statusFilter ? { status: statusFilter } : {}),
            ...(dateFilter ? { date: dateFilter } : {}),
          },
        })
      ).data,
    [statusFilter, dateFilter],
  );
  const criteria = useLoad<any>(
    async () => (await api.get("/admin/clinic/eval-criteria")).data,
    [],
  );

  const act = async (fn: () => Promise<any>, describe: (data: any) => string) => {
    setError(null);
    setOk(null);
    try {
      const { data } = await fn();
      setOk(describe(data));
      await queue.reload();
    } catch (e) {
      setError(errMsg(e));
    }
  };

  return (
    <section>
      <h2>클리닉 관리</h2>
      <p className="inline">
        상태:{" "}
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="">전체</option>
          {["대기", "승인배정", "미승인", "취소"].map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </select>
        날짜:{" "}
        <input type="date" value={dateFilter} onChange={(e) => setDateFilter(e.target.value)} />
        <button onClick={() => setDateFilter("")}>날짜 해제</button>
      </p>
      <Msg error={queue.error ?? error} ok={ok} />
      {queue.data && (
        <table>
          <thead>
            <tr>
              <th>번호</th>
              <th>학생(노쇼/제한)</th>
              <th>날짜·시간</th>
              <th>상태</th>
              <th>배정 조교</th>
              <th>클리닉 출결</th>
              <th>처리</th>
            </tr>
          </thead>
          <tbody>
            {queue.data.requests.length === 0 && (
              <tr>
                <td colSpan={7} className="muted">
                  신청 없음
                </td>
              </tr>
            )}
            {queue.data.requests.map((row: any) => (
              <QueueRow
                key={row.clinic_id}
                row={row}
                myUserId={me?.user_id ?? 0}
                act={act}
                onEval={() => setEvalTarget(evalTarget === row.clinic_id ? null : row.clinic_id)}
              />
            ))}
          </tbody>
        </table>
      )}
      {evalTarget !== null && criteria.data && (
        <EvaluationForm
          clinicId={evalTarget}
          criteria={criteria.data.criteria}
          act={act}
          onDone={() => setEvalTarget(null)}
        />
      )}

      <h3>평가 항목 마스터</h3>
      <Msg error={criteria.error} />
      {criteria.data && (
        <table>
          <thead>
            <tr>
              <th>순서</th>
              <th>항목</th>
              <th>기준 설명</th>
            </tr>
          </thead>
          <tbody>
            {criteria.data.criteria.map((row: any) => (
              <tr key={row.criteria_id}>
                <td>{row.display_order ?? "-"}</td>
                <td>{row.item}</td>
                <td>{row.description ?? "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function QueueRow({
  row,
  myUserId,
  act,
  onEval,
}: {
  row: any;
  myUserId: number;
  act: (fn: () => Promise<any>, describe: (data: any) => string) => Promise<void>;
  onEval: () => void;
}) {
  const [staffId, setStaffId] = useState(String(myUserId || ""));
  const [meetUrl, setMeetUrl] = useState("https://meet.google.com/bare-demo");
  return (
    <tr>
      <td>{row.clinic_id}</td>
      <td>
        {row.student.name} (원번 {row.student.unique_id}) — 노쇼 {row.student.noshow_count}회
        {row.student.clinic_banned && <strong className="error"> · 제한 중</strong>}
        {row.student.clinic_banned && (
          <div>
            <button
              onClick={() =>
                act(
                  () => api.post(`/admin/clinic/students/${row.student.student_id}/unban`),
                  (data) =>
                    `제한 해제 완료 — 노쇼 ${data.noshow_count}회로 초기화 (대표 전용 API)`,
                )
              }
            >
              제한 해제(대표 전용)
            </button>
          </div>
        )}
      </td>
      <td>
        {row.requested_date} {row.requested_time}
      </td>
      <td>{row.status}</td>
      <td>
        {row.assigned_staff ? row.assigned_staff.name : "-"}
        {row.meet_url && (
          <div className="muted">
            <a href={row.meet_url} target="_blank" rel="noreferrer">
              미트 링크
            </a>
          </div>
        )}
      </td>
      <td>{row.attendance_status ?? "-"}</td>
      <td>
        <div className="inline">
          <input
            type="number"
            placeholder="staff user_id"
            value={staffId}
            onChange={(e) => setStaffId(e.target.value)}
            style={{ width: 90 }}
          />
          <input
            placeholder="meet_url"
            value={meetUrl}
            onChange={(e) => setMeetUrl(e.target.value)}
            style={{ width: 200 }}
          />
          <button
            onClick={() =>
              act(
                () =>
                  api.post(`/admin/clinic/requests/${row.clinic_id}/assign`, {
                    assigned_staff_id: Number(staffId),
                    meet_url: meetUrl,
                  }),
                () => `#${row.clinic_id} 승인+배정 완료`,
              )
            }
          >
            승인+배정
          </button>
          <button
            onClick={() =>
              act(
                () => api.post(`/admin/clinic/requests/${row.clinic_id}/reject`),
                () => `#${row.clinic_id} 미승인 처리`,
              )
            }
          >
            미승인
          </button>
        </div>
        <div className="inline">
          <button
            onClick={() =>
              act(
                () =>
                  api.post(`/admin/clinic/requests/${row.clinic_id}/attendance`, {
                    status: "출석",
                  }),
                () => `#${row.clinic_id} 출석 처리(학부모 알림 행 생성)`,
              )
            }
          >
            출석 처리
          </button>
          <button
            onClick={() =>
              act(
                () =>
                  api.post(`/admin/clinic/requests/${row.clinic_id}/attendance`, {
                    status: "결석",
                  }),
                (data) =>
                  `#${row.clinic_id} 결석(노쇼) 처리 — 누적 ${data.student.noshow_count}회${
                    data.student.clinic_banned ? " · 영구 제한 발동" : ""
                  }`,
              )
            }
          >
            결석(노쇼) 처리
          </button>
          <button onClick={onEval}>평가 입력</button>
        </div>
      </td>
    </tr>
  );
}

function EvaluationForm({
  clinicId,
  criteria,
  act,
  onDone,
}: {
  clinicId: number;
  criteria: any[];
  act: (fn: () => Promise<any>, describe: (data: any) => string) => Promise<void>;
  onDone: () => void;
}) {
  const [results, setResults] = useState<Record<number, string>>({});
  const [overall, setOverall] = useState("");
  return (
    <fieldset>
      <legend>클리닉 #{clinicId} 조교 수행 평가</legend>
      <table>
        <tbody>
          {criteria.map((item) => (
            <tr key={item.criteria_id}>
              <td>{item.item}</td>
              <td>
                {["충족", "미충족"].map((value) => (
                  <label key={value} style={{ marginRight: 8 }}>
                    <input
                      type="radio"
                      name={`crit-${clinicId}-${item.criteria_id}`}
                      checked={results[item.criteria_id] === value}
                      onChange={() =>
                        setResults({ ...results, [item.criteria_id]: value })
                      }
                    />
                    {value}
                  </label>
                ))}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="inline">
        종합 판정:{" "}
        <select value={overall} onChange={(e) => setOverall(e.target.value)}>
          <option value="">미판정</option>
          <option value="적격">적격</option>
          <option value="부적격">부적격</option>
        </select>
        <button
          onClick={() =>
            act(
              () =>
                api.post(`/admin/clinic/requests/${clinicId}/evaluation`, {
                  items: Object.entries(results).map(([criteriaId, result]) => ({
                    criteria_id: Number(criteriaId),
                    result,
                  })),
                  ...(overall ? { overall_result: overall } : {}),
                }),
              () => `#${clinicId} 평가 저장 완료`,
            ).then(onDone)
          }
        >
          평가 저장
        </button>
        <button onClick={onDone}>닫기</button>
      </p>
    </fieldset>
  );
}

/** 워크북 관리 — 업로드(멀티파트)/목록/매칭(수동·원번 대조)/삭제 (PRD 3.1.7). */
/* eslint-disable @typescript-eslint/no-explicit-any */
import { FormEvent, useRef, useState } from "react";

import { api, errMsg, mediaUrl } from "../../api";
import { Msg, useLoad } from "../../ui";

export default function WorkbookAdminPage() {
  const [statusFilter, setStatusFilter] = useState("");
  const [sessionFilter, setSessionFilter] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);

  const list = useLoad<any>(
    async () =>
      (
        await api.get("/admin/workbook", {
          params: {
            ...(statusFilter ? { status: statusFilter } : {}),
            ...(sessionFilter ? { session_id: sessionFilter } : {}),
          },
        })
      ).data,
    [statusFilter, sessionFilter],
  );

  const act = async (fn: () => Promise<unknown>, okMessage: string) => {
    setError(null);
    setOk(null);
    try {
      await fn();
      setOk(okMessage);
      await list.reload();
    } catch (e) {
      setError(errMsg(e));
    }
  };

  return (
    <section>
      <h2>워크북 관리</h2>
      <UploadForm onDone={() => list.reload()} />
      <h3>업로드 목록·보정</h3>
      <p className="inline">
        상태 필터:{" "}
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="">전체</option>
          {["대기", "자동매칭", "수동확정", "불일치", "인식실패"].map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </select>
        회차 필터:{" "}
        <input
          type="number"
          placeholder="session_id"
          value={sessionFilter}
          onChange={(e) => setSessionFilter(e.target.value)}
          style={{ width: 90 }}
        />
      </p>
      <Msg error={list.error ?? error} ok={ok} />
      {list.data && (
        <>
          <p className="muted">
            총 {list.data.total_count}건 · 미매핑(보정 잔량) {list.data.unmatched_count}건
          </p>
          <table>
            <thead>
              <tr>
                <th>번호</th>
                <th>사진</th>
                <th>학생(잠정/확정)</th>
                <th>인식값(원번/이름)</th>
                <th>상태</th>
                <th>회차</th>
                <th>업로더</th>
                <th>매칭 보정</th>
                <th>삭제</th>
              </tr>
            </thead>
            <tbody>
              {list.data.submissions.map((row: any) => (
                <MatchRow key={row.submission_id} row={row} act={act} />
              ))}
            </tbody>
          </table>
        </>
      )}
    </section>
  );
}

function UploadForm({ onDone }: { onDone: () => void }) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [studentId, setStudentId] = useState("");
  const [sessionId, setSessionId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setOk(null);
    const files = fileRef.current?.files;
    if (!files || files.length === 0) {
      setError("이미지 파일을 선택하세요(jpg/jpeg/png/webp, 장당 10MB 이하).");
      return;
    }
    const form = new FormData();
    for (const file of Array.from(files)) form.append("images", file);
    form.append("student_id", studentId);
    if (sessionId) form.append("session_id", sessionId);
    try {
      const { data } = await api.post("/admin/workbook/upload", form, {
        headers: { "Content-Type": null as unknown as string },
      });
      setOk(`업로드 완료 — ${data.submissions.length}장(매핑 대기 상태로 생성)`);
      if (fileRef.current) fileRef.current.value = "";
      onDone();
    } catch (e) {
      setError(errMsg(e));
    }
  };

  return (
    <>
      <h3>사진 업로드 (조교)</h3>
      <form onSubmit={submit} className="inline">
        <input ref={fileRef} type="file" multiple accept=".jpg,.jpeg,.png,.webp" />
        <input
          type="number"
          placeholder="student_id(잠정 매핑)"
          value={studentId}
          onChange={(e) => setStudentId(e.target.value)}
        />
        <input
          type="number"
          placeholder="session_id(선택)"
          value={sessionId}
          onChange={(e) => setSessionId(e.target.value)}
        />
        <button type="submit">업로드</button>
      </form>
      <Msg error={error} ok={ok} />
    </>
  );
}

function MatchRow({
  row,
  act,
}: {
  row: any;
  act: (fn: () => Promise<unknown>, okMessage: string) => Promise<void>;
}) {
  const [manualId, setManualId] = useState("");
  const [uniqueId, setUniqueId] = useState("");
  const [name, setName] = useState("");
  return (
    <tr>
      <td>{row.submission_id}</td>
      <td>
        <a href={mediaUrl(row.image_url)} target="_blank" rel="noreferrer">
          <img className="thumb" src={mediaUrl(row.image_url)} alt="워크북" />
        </a>
      </td>
      <td>
        {row.student.name} (원번 {row.student.matching_key})
      </td>
      <td>
        {row.recognized_matching_key ?? "-"} / {row.recognized_name ?? "-"}
      </td>
      <td>{row.match_status ?? "대기"}</td>
      <td>{row.session ? `${row.session.session_date}` : "-"}</td>
      <td>{row.uploaded_by?.name ?? "-"}</td>
      <td>
        <div className="inline">
          <input
            type="number"
            placeholder="student_id"
            value={manualId}
            onChange={(e) => setManualId(e.target.value)}
            style={{ width: 90 }}
          />
          <button
            onClick={() =>
              act(
                () =>
                  api.patch(`/admin/workbook/${row.submission_id}/match`, {
                    student_id: Number(manualId),
                  }),
                `#${row.submission_id} 수동확정 완료`,
              )
            }
          >
            수동확정
          </button>
        </div>
        <div className="inline">
          <input
            placeholder="원번"
            value={uniqueId}
            onChange={(e) => setUniqueId(e.target.value)}
            style={{ width: 70 }}
          />
          <input
            placeholder="이름"
            value={name}
            onChange={(e) => setName(e.target.value)}
            style={{ width: 70 }}
          />
          <button
            onClick={() =>
              act(
                () =>
                  api.patch(`/admin/workbook/${row.submission_id}/match`, {
                    recognized_matching_key: uniqueId,
                    recognized_name: name,
                  }),
                `#${row.submission_id} 원번+이름 대조 시도 완료(결과는 상태 열 확인)`,
              )
            }
          >
            원번 대조
          </button>
        </div>
      </td>
      <td>
        <button
          onClick={() =>
            act(
              () => api.delete(`/admin/workbook/${row.submission_id}`),
              `#${row.submission_id} 삭제 완료(파일 포함)`,
            )
          }
        >
          삭제
        </button>
      </td>
    </tr>
  );
}

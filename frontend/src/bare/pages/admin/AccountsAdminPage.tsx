/** 계정 일괄 발급 — 명단 붙여넣기 → 행별 결과(초기 비번 1회 노출) + 등록 전환. */
/* eslint-disable @typescript-eslint/no-explicit-any */
import { FormEvent, useState } from "react";

import { api, errMsg } from "../../api";
import { Msg } from "../../ui";

const PLACEHOLDER = `이름,휴대폰,학부모휴대폰,원번,학년,학교 — 한 줄에 한 명(빈 칸은 비워둠)
예)
홍길동,01099990001,01088880001,26901,고2,세화고
김철수,,01088880002,26902,고2,반포고`;

export default function AccountsAdminPage() {
  const [text, setText] = useState("");
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [registerId, setRegisterId] = useState("");
  const [registerMsg, setRegisterMsg] = useState<string | null>(null);
  const [registerError, setRegisterError] = useState<string | null>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setResult(null);
    const rows = text
      .split("\n")
      .map((line) => line.trim())
      .filter((line) => line.length > 0)
      .map((line) => {
        const [name, phone, parentPhone, uniqueId, grade, school] = line
          .split(",")
          .map((cell) => cell.trim());
        return {
          name,
          phone: phone || "",
          parent_phone: parentPhone || "",
          unique_id: uniqueId || "",
          grade: grade || "",
          school: school || "",
        };
      });
    try {
      const { data } = await api.post("/admin/accounts/bulk", rows);
      setResult(data);
    } catch (e) {
      setError(errMsg(e));
    }
  };

  const register = async (event: FormEvent) => {
    event.preventDefault();
    setRegisterError(null);
    setRegisterMsg(null);
    try {
      const { data } = await api.post(`/admin/accounts/${registerId}/register`);
      setRegisterMsg(
        `학생 #${data.student_id} 등록 전환 완료 (${data.registered_at}) — 전체 기능 개방`,
      );
    } catch (e) {
      setRegisterError(errMsg(e));
    }
  };

  return (
    <section>
      <h2>계정 일괄 발급</h2>
      <p className="muted">
        아이디=본인 휴대폰(무전화 학생은 학부모번호+접미사 a,b,…). 학부모 번호가 기존
        학부모와 같으면 자녀 연결만 추가. 행 단위 실패 — 한 행이 중복이어도 나머지는
        생성된다.
      </p>
      <form onSubmit={submit}>
        <p>
          <textarea
            rows={6}
            placeholder={PLACEHOLDER}
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
        </p>
        <button type="submit">일괄 발급</button>
      </form>
      <Msg error={error} />
      {result && (
        <>
          <p className="ok">
            생성 {result.summary.created}명 · 실패 {result.summary.failed}명 · 학부모 신규{" "}
            {result.summary.parents_created}명 · 기존 연결 {result.summary.parents_linked}명
          </p>
          <table>
            <thead>
              <tr>
                <th>행</th>
                <th>이름</th>
                <th>결과</th>
                <th>학생 아이디</th>
                <th>초기 비밀번호(1회 노출)</th>
                <th>학부모</th>
                <th>실패 사유</th>
              </tr>
            </thead>
            <tbody>
              {result.results.map((row: any) => (
                <tr key={row.index}>
                  <td>{row.index + 1}</td>
                  <td>{row.name ?? "-"}</td>
                  <td>{row.status}</td>
                  <td>{row.login_id ?? "-"}</td>
                  <td>{row.initial_password ?? "-"}</td>
                  <td>
                    {row.parent
                      ? row.parent.created
                        ? `신규 (${row.parent.login_id} / ${row.parent.initial_password})`
                        : `기존 학부모에 연결 (${row.parent.login_id ?? "-"})`
                      : "-"}
                  </td>
                  <td className="error">{row.error ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      <h2>예비등록 → 등록 전환</h2>
      <p className="muted">
        1주차 실제 출석 확인 후 전환(PRD 3.1.5). 이미 등록/퇴원 상태면 400 사유 표시.
      </p>
      <form onSubmit={register} className="inline">
        <input
          type="number"
          placeholder="student_id"
          value={registerId}
          onChange={(e) => setRegisterId(e.target.value)}
        />
        <button type="submit">등록 전환</button>
      </form>
      <Msg error={registerError} ok={registerMsg} />
    </section>
  );
}

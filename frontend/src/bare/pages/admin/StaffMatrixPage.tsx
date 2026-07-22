/** 권한 매트릭스(대표 전용) — 직원×기능 체크박스, 프리셋 ⊕ delta 시연. */
/* eslint-disable @typescript-eslint/no-explicit-any */
import { FormEvent, useState } from "react";

import { api, errMsg } from "../../api";
import { Msg, useLoad } from "../../ui";

export default function StaffMatrixPage() {
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);
  // 직원별 체크 상태 오버라이드(저장 전) — {user_id: {feature_key: bool}}
  const [dirty, setDirty] = useState<Record<number, Record<string, boolean>>>({});

  const matrix = useLoad<any>(async () => (await api.get("/admin/staff")).data, []);

  const act = async (fn: () => Promise<any>, describe: (data: any) => string) => {
    setError(null);
    setOk(null);
    try {
      const { data } = await fn();
      setOk(describe(data));
      setDirty({});
      await matrix.reload();
    } catch (e) {
      setError(errMsg(e));
    }
  };

  const data = matrix.data;
  const checked = (staff: any, key: string): boolean =>
    dirty[staff.user_id]?.[key] ?? staff.effective.includes(key);

  const toggle = (staff: any, key: string) =>
    setDirty((prev) => ({
      ...prev,
      [staff.user_id]: {
        ...prev[staff.user_id],
        [key]: !checked(staff, key),
      },
    }));

  const save = (staff: any) => {
    const changes = dirty[staff.user_id];
    if (!changes || Object.keys(changes).length === 0) {
      setError("변경된 체크가 없습니다.");
      return;
    }
    void act(
      () => api.put(`/admin/staff/${staff.user_id}/features`, changes),
      (row) =>
        `${row.name} 저장 완료 — delta 추가 [${row.delta.added.join(", ") || "없음"}] · 회수 [${
          row.delta.removed.join(", ") || "없음"
        }] (프리셋과 같아진 delta 는 자동 정리)`,
    );
  };

  return (
    <section>
      <h2>직원 권한 매트릭스 (대표 전용)</h2>
      <p className="muted">
        체크 상태 = 유효 기능(역할 프리셋 ⊕ delta). 체크를 바꿔 저장하면 프리셋과의 편차만
        delta 로 저장된다. P=프리셋 포함 기능.
      </p>
      <Msg error={matrix.error ?? error} ok={ok} />
      {data && (
        <table>
          <thead>
            <tr>
              <th>직원</th>
              <th>역할</th>
              <th>활성</th>
              {data.feature_keys.map((key: string) => (
                <th key={key}>{key}</th>
              ))}
              <th>저장/비활성</th>
            </tr>
          </thead>
          <tbody>
            {data.staff.map((staff: any) => (
              <tr key={staff.user_id}>
                <td>
                  {staff.name}
                  <div className="muted">{staff.login_id}</div>
                </td>
                <td>{staff.role}</td>
                <td>{staff.is_active ? "활성" : "비활성"}</td>
                {data.feature_keys.map((key: string) => (
                  <td key={key}>
                    <label>
                      <input
                        type="checkbox"
                        checked={checked(staff, key)}
                        onChange={() => toggle(staff, key)}
                      />
                      {staff.preset.includes(key) ? " P" : ""}
                    </label>
                  </td>
                ))}
                <td className="inline">
                  <button onClick={() => save(staff)}>저장</button>
                  <button
                    onClick={() =>
                      act(
                        () => api.patch(`/admin/staff/${staff.user_id}/deactivate`),
                        (row) => `${row.name} 비활성 처리(로그인 차단)`,
                      )
                    }
                  >
                    비활성
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <CreateStaffForm
        onCreated={(row) => {
          setOk(
            `직원 생성 — ${row.name} (${row.login_id}) 초기 비밀번호 ${row.initial_password} (1회 노출·최초 로그인 시 변경 강제)`,
          );
          void matrix.reload();
        }}
        onError={setError}
      />
    </section>
  );
}

function CreateStaffForm({
  onCreated,
  onError,
}: {
  onCreated: (row: any) => void;
  onError: (message: string) => void;
}) {
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [role, setRole] = useState("관리자");

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    try {
      const { data } = await api.post("/admin/staff", { name, phone, role });
      onCreated(data);
      setName("");
      setPhone("");
    } catch (e) {
      onError(errMsg(e));
    }
  };

  return (
    <fieldset>
      <legend>직원 계정 생성</legend>
      <form onSubmit={submit} className="inline">
        <input placeholder="이름" value={name} onChange={(e) => setName(e.target.value)} />
        <input
          placeholder="전화번호(=아이디)"
          value={phone}
          onChange={(e) => setPhone(e.target.value)}
        />
        <select value={role} onChange={(e) => setRole(e.target.value)}>
          <option value="관리자">관리자</option>
          <option value="조교">조교</option>
        </select>
        <button type="submit">생성</button>
      </form>
    </fieldset>
  );
}

/** 비밀번호 변경 — 현재 비밀번호 검증 + Django 비밀번호 정책 오류 표시. */
import { FormEvent, useState } from "react";

import { useMe } from "../MeContext";
import { api, errMsg } from "../api";
import { Msg } from "../ui";

export default function PasswordPage() {
  const { refresh } = useMe();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setOk(null);
    try {
      await api.post("/auth/password", { current_password: current, new_password: next });
      setOk("비밀번호가 변경되었습니다(세션 유지 — must_change_password 해제).");
      setCurrent("");
      setNext("");
      await refresh();
    } catch (e) {
      setError(errMsg(e));
    }
  };

  return (
    <section>
      <h2>비밀번호 변경</h2>
      <p className="muted">
        너무 짧거나 흔한 비밀번호는 Django 정책 검증(400)에 걸린다 — 오류 본문이 그대로
        표시되니 눌러서 확인해 보세요.
      </p>
      <form onSubmit={submit} className="inline">
        <input
          type="password"
          placeholder="현재 비밀번호"
          value={current}
          onChange={(e) => setCurrent(e.target.value)}
        />
        <input
          type="password"
          placeholder="새 비밀번호"
          value={next}
          onChange={(e) => setNext(e.target.value)}
        />
        <button type="submit">변경</button>
      </form>
      <Msg error={error} ok={ok} />
    </section>
  );
}

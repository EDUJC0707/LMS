/** 로그인 3종(학생/학부모/관리자) — 경로 분리 시연 + 로그아웃. */
import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";

import { useMe } from "../MeContext";
import { api, errMsg } from "../api";
import { Msg } from "../ui";

const FORMS: Array<{ key: string; label: string; url: string; hint: string; home: string }> = [
  {
    key: "student",
    label: "학생 로그인",
    url: "/auth/login",
    hint: "예: 김하늘0001 / test1234",
    home: "/bare/student/home",
  },
  {
    key: "parent",
    label: "학부모 로그인",
    url: "/auth/login",
    hint: "예: 김하늘0001p / test1234",
    home: "/bare/parent/home",
  },
  {
    key: "admin",
    label: "관리자 로그인(대표·관리자·조교)",
    url: "/auth/login/admin",
    hint: "예: 김관리0002 / test1234",
    home: "/bare",
  },
];

function LoginForm({ form }: { form: (typeof FORMS)[number] }) {
  const { refresh } = useMe();
  const navigate = useNavigate();
  const [loginId, setLoginId] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    try {
      await api.post(form.url, { login_id: loginId, password });
      await refresh();
      navigate(form.home);
    } catch (e) {
      setError(errMsg(e));
    }
  };

  return (
    <fieldset>
      <legend>{form.label}</legend>
      <form onSubmit={submit} className="inline">
        <input
          placeholder="아이디(전화번호)"
          value={loginId}
          onChange={(e) => setLoginId(e.target.value)}
        />
        <input
          type="password"
          placeholder="비밀번호"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <button type="submit">로그인</button>
        <span className="muted"> {form.hint}</span>
      </form>
      <Msg error={error} />
    </fieldset>
  );
}

export default function LoginPage() {
  const { me } = useMe();
  return (
    <section>
      <h2>로그인</h2>
      {me && (
        <p>
          현재 <strong>{me.name}</strong>({me.role}) 로 로그인되어 있습니다. 다른 계정으로
          로그인하면 세션이 교체됩니다.
        </p>
      )}
      <p className="muted">
        역할이 맞지 않는 경로로 로그인하면 403(동일 메시지)이 떨어진다 — 경로별 역할 게이트 시연.
      </p>
      {FORMS.map((form) => (
        <LoginForm key={form.key} form={form} />
      ))}
    </section>
  );
}

/**
 * 로그인 — 중앙 정렬 단일 카드.
 *
 * 소비자(학생·학부모)는 `/login` 하나를 공유한다. 성공 응답의 role 로 홈이
 * 갈린다. 직원용 `/login/admin` 은 같은 화면을 쓰되 어디서도 링크하지 않는다.
 *
 * 화면 구성은 로고·제목·아이디·비밀번호·버튼이 전부다. 안내 문구를 넣지 않는다
 * (CLAUDE.md §8). 서버가 거절한 이유만 폼 위에 그대로 띄운다.
 */
import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";

import { LoginKind, login } from "../../api/auth";
import { toMessage } from "../../api/errors";
import { homePathFor } from "../../api/types";
import { useMe } from "../../auth/MeProvider";
import { Alert, Button, Input } from "../../components";

export function LoginPage({ kind }: { kind: LoginKind }) {
  const { refresh } = useMe();
  const navigate = useNavigate();
  const [loginId, setLoginId] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setPending(true);
    try {
      const me = await login(kind, loginId.trim(), password);
      await refresh();
      navigate(me.must_change_password ? "/password" : homePathFor(me.role), { replace: true });
    } catch (caught) {
      setError(toMessage(caught));
      setPending(false);
    }
  };

  return (
    <main className="ui-authpage">
      <div className="ui-authcard">
        {/* 화면당 h1 하나 — 브랜드 줄이 그 역할을 한다. 별도 "로그인" 제목은
            버튼과 중복이라 뺐다(2026-07-28 사용자 판단). */}
        <h1 className="ui-authcard__brand">
          <img src="/atom-master.png" alt="" width={40} height={40} />
          <span className="ui-authcard__brandname">한종철 통합과학 LMS</span>
        </h1>

        <form className="ui-authcard__form" onSubmit={submit} noValidate>
          {error && <Alert tone="danger">{error}</Alert>}

          {/* 로그인 화면만 라벨 없이 placeholder 로 간다(2026-07-28 사용자 지시).
              칸이 둘뿐이고 아이디·비밀번호는 설명이 필요 없는 쌍이라 라벨이
              중복이다. 스크린리더용 이름은 aria-label 로 유지한다.
              **다른 화면은 Field 라벨 규칙 그대로** — 여기만 예외다. */}
          <Input
            name="login_id"
            type="text"
            aria-label="아이디"
            placeholder="아이디"
            autoComplete="username"
            required
            value={loginId}
            onChange={(event) => setLoginId(event.target.value)}
            autoFocus
          />

          <Input
            name="password"
            type="password"
            aria-label="비밀번호"
            placeholder="비밀번호"
            autoComplete="current-password"
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />

          <Button type="submit" variant="primary" block loading={pending}>
            로그인
          </Button>
        </form>
      </div>
    </main>
  );
}

/** 학생·학부모 공용. */
export function ConsumerLoginPage() {
  return <LoginPage kind="consumer" />;
}

/** 직원 전용 — 링크 없음. 주소를 아는 사람만 들어온다. */
export function AdminLoginPage() {
  return <LoginPage kind="admin" />;
}

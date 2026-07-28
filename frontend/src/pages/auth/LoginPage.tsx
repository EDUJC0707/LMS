/**
 * 로그인 3종(학생 / 학부모 / 관리자) — PRD §4 경로 분리.
 * 세 화면은 같은 컴포넌트를 쓰고, 어떤 계정 종류인지만 다르다.
 * 역할이 맞지 않는 경로로 로그인하면 서버가 403 을 주고, 그 문구를 그대로 띄운다.
 */
import { FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { LoginKind, login } from "../../api/auth";
import { toMessage } from "../../api/errors";
import { homePathFor } from "../../api/types";
import { useMe } from "../../auth/MeProvider";
import { Alert, Button, Field, Input } from "../../components";

interface Copy {
  kind: LoginKind;
  title: string;
  sub: string;
  idLabel: string;
  idHint: string;
  lede: string;
  note: string;
}

const COPY: Record<LoginKind, Copy> = {
  student: {
    kind: "student",
    title: "학생 로그인",
    sub: "학원에 등록할 때 적어 낸 본인 휴대폰 번호로 들어옵니다.",
    idLabel: "본인 휴대폰 번호",
    idHint: "'-' 없이 숫자만 입력하세요.",
    lede: "오늘 배운 것과, 다음에 해야 할 것.",
    note: "출결·성적·클리닉 신청·워크북을 한곳에서 확인합니다.",
  },
  parent: {
    kind: "parent",
    title: "학부모 로그인",
    sub: "학원에 등록된 보호자 휴대폰 번호로 들어옵니다.",
    idLabel: "보호자 휴대폰 번호",
    idHint: "'-' 없이 숫자만 입력하세요. 자녀가 여럿이면 로그인 후 고를 수 있습니다.",
    lede: "자녀가 오늘 무엇을 했는지, 정확히.",
    note: "출결·성적·워크북을 보호자 화면에서 그대로 확인합니다.",
  },
  admin: {
    kind: "admin",
    title: "직원 로그인",
    sub: "대표·관리자·조교 계정으로 들어옵니다.",
    idLabel: "휴대폰 번호",
    idHint: "'-' 없이 숫자만 입력하세요.",
    lede: "출결부터 성적 처리까지, 한 콘솔에서.",
    note: "권한이 있는 기능만 메뉴에 나타납니다.",
  },
};

const SWITCH: { to: string; label: string; kind: LoginKind }[] = [
  { to: "/login/student", label: "학생", kind: "student" },
  { to: "/login/parent", label: "학부모", kind: "parent" },
  { to: "/login/admin", label: "직원", kind: "admin" },
];

export function LoginPage({ kind }: { kind: LoginKind }) {
  const copy = COPY[kind];
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
    <div className="ui-authpage">
      <aside className="ui-authpage__aside on-navy">
        <img
          className="ui-authpage__mark"
          src="/atom-logo.png"
          alt=""
          width={72}
          height={72}
        />
        <p className="ui-authpage__lede">{copy.lede}</p>
        <p className="ui-authpage__note">{copy.note}</p>
      </aside>

      <div className="ui-authpage__panel">
        <div className="ui-authcard">
          <div className="ui-authcard__brand">
            <img src="/atom-logo.png" alt="" width={28} height={28} />
            <span className="ui-authcard__brandname">한종철 통합과학 LMS</span>
          </div>

          <h1 className="ui-authcard__title">{copy.title}</h1>
          <p className="ui-authcard__sub">{copy.sub}</p>

          <form className="ui-authcard__form" onSubmit={submit} noValidate>
            {error && <Alert tone="danger">{error}</Alert>}

            <Field label={copy.idLabel} hint={copy.idHint} required>
              {(props) => (
                <Input
                  {...props}
                  name="login_id"
                  type="tel"
                  inputMode="numeric"
                  autoComplete="username"
                  placeholder="01012345678"
                  value={loginId}
                  onChange={(event) => setLoginId(event.target.value)}
                  autoFocus
                />
              )}
            </Field>

            <Field label="비밀번호" required>
              {(props) => (
                <Input
                  {...props}
                  name="password"
                  type="password"
                  autoComplete="current-password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                />
              )}
            </Field>

            <Button type="submit" variant="primary" block loading={pending}>
              로그인
            </Button>
          </form>

          <div className="ui-authcard__switch">
            <span>다른 계정으로 들어가기</span>
            {SWITCH.filter((item) => item.kind !== kind).map((item) => (
              <Link key={item.to} to={item.to}>
                {item.label}
              </Link>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

export function StudentLoginPage() {
  return <LoginPage kind="student" />;
}
export function ParentLoginPage() {
  return <LoginPage kind="parent" />;
}
export function AdminLoginPage() {
  return <LoginPage kind="admin" />;
}

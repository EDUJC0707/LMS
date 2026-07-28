/**
 * 비밀번호 변경. must_change_password 인 계정은 가드가 여기로 강제 유도하며,
 * 변경 전에는 다른 화면으로 나갈 수 없다(RequireAuth 참조).
 */
import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";

import { changePassword } from "../../api/auth";
import { toMessage } from "../../api/errors";
import { homePathFor } from "../../api/types";
import { useMe } from "../../auth/MeProvider";
import { Alert, Button, Card, Field, Input, PageHeader } from "../../components";

export default function PasswordPage() {
  const { me, refresh } = useMe();
  const navigate = useNavigate();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [mismatch, setMismatch] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [done, setDone] = useState(false);

  const forced = me?.must_change_password ?? false;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setMismatch(null);
    if (next !== confirm) {
      setMismatch("새 비밀번호가 서로 다릅니다. 두 칸에 같은 값을 입력해 주세요.");
      return;
    }
    setPending(true);
    try {
      await changePassword(current, next);
      await refresh();
      setDone(true);
      setCurrent("");
      setNext("");
      setConfirm("");
      if (forced && me) navigate(homePathFor(me.role), { replace: true });
    } catch (caught) {
      setError(toMessage(caught));
    } finally {
      setPending(false);
    }
  };

  return (
    <>
      <PageHeader
        title="비밀번호 변경"
        description={
          forced
            ? "처음 발급받은 비밀번호를 쓰고 계십니다. 본인만 아는 비밀번호로 바꾼 뒤에 이용할 수 있습니다."
            : "다른 곳에서 쓰지 않는 비밀번호로 바꿔 주세요."
        }
      />

      <Card>
        <form
          onSubmit={submit}
          noValidate
          style={{ display: "grid", gap: "var(--space-sm)", maxWidth: "24rem" }}
        >
          {forced && <Alert tone="warning">비밀번호를 바꿔야 다른 화면을 볼 수 있습니다.</Alert>}
          {error && <Alert tone="danger">{error}</Alert>}
          {done && !forced && <Alert tone="success">비밀번호를 바꿨습니다.</Alert>}

          <Field label="현재 비밀번호" required>
            {(props) => (
              <Input
                {...props}
                type="password"
                autoComplete="current-password"
                value={current}
                onChange={(event) => setCurrent(event.target.value)}
              />
            )}
          </Field>

          <Field
            label="새 비밀번호"
            hint="8자 이상, 너무 흔한 비밀번호는 사용할 수 없습니다."
            required
          >
            {(props) => (
              <Input
                {...props}
                type="password"
                autoComplete="new-password"
                value={next}
                onChange={(event) => setNext(event.target.value)}
              />
            )}
          </Field>

          <Field label="새 비밀번호 확인" error={mismatch} required>
            {(props) => (
              <Input
                {...props}
                type="password"
                autoComplete="new-password"
                value={confirm}
                onChange={(event) => setConfirm(event.target.value)}
              />
            )}
          </Field>

          <div className="ui-row">
            <Button type="submit" variant="primary" loading={pending}>
              비밀번호 바꾸기
            </Button>
          </div>
        </form>
      </Card>
    </>
  );
}

/**
 * /admin/students/:studentId — 학생 상세·수정 (FLOW 2-6).
 *
 * API  GET   /api/admin/students/{id}
 *      PATCH /api/admin/students/{id}   {name?, school?, grade?, phone?, parent_phone?}
 *      POST  /api/admin/notifications/{id}/resend
 *
 * 화면 설계
 * - **고칠 자리가 여기 하나뿐이다.** 번호가 한 자리 틀리게 들어온 학생은 계속 남의
 *   번호로 문자·청구를 받고, 아이디·대조키도 그 번호에서 나온 채 남는다.
 * - **아이디·대조키는 입력칸이 아니다**(FLOW 2-3 파생값). 이름·번호에서 서버가
 *   만들고, 번호를 고치면 서버가 다시 만들어 응답으로 돌려준다.
 * - **바뀐 칸만 보낸다.** 전부 보내면 손대지 않은 이름까지 같은 값으로 다시 저장되고,
 *   서버는 "이름이 왔다"만 보고 파생값 재계산 경로로 들어간다.
 * - **새 비밀번호는 화면에 남긴다**(토스트 아님). 해시만 저장되므로 이 응답이
 *   지나가면 다시 볼 수 없다 — 계정 안내 알림이 나가기 전까지 유일한 전달 경로다.
 * - 발송 내역의 **보낸 번호**는 그때 나간 번호다(서버 스냅샷). 지금 칸에 적힌 번호와
 *   다를 수 있고, 다른 것이 정상이다 — "못 받았다"는 연락에 답하는 자리가 여기다.
 * - **어느 줄이든 다시 보낼 수 있다**(FLOW 3-11). 번호를 고친 뒤 여기서 누르면
 *   새 번호로 나간다 — 유형을 가리지 않는다.
 */
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { http, useApi, useApiAction } from "../../../api";
import {
  Alert,
  Button,
  Card,
  EmptyState,
  ErrorState,
  Field,
  Input,
  Loading,
  StatusBadge,
  Table,
} from "../../../components";
import "./manage.css";

interface ParentBlock {
  parent_id: number;
  name: string | null;
  phone: string;
  login_id: string | null;
}

interface ClassBlock {
  class_id: number | null;
  class_name: string | null;
  course_name: string;
  status: string;
}

interface OrderBlock {
  order_id: number;
  product_name: string;
  amount: number;
  status: string;
  is_billed: boolean;
  billed_to_phone: string | null;
  ordered_at: string | null;
  paid_at: string | null;
}

interface NotificationBlock {
  notif_id: number;
  target: { kind: string; name: string } | null;
  type: string;
  channel: string;
  status: string;
  /** 그때 나간 번호. 값이 생기기 전의 행은 비어 있다. */
  sent_to_phone: string;
  error_msg: string | null;
  sent_at: string | null;
  created_at: string | null;
}

interface StudentDetail {
  student_id: number;
  name: string | null;
  login_id: string | null;
  matching_key: string;
  phone: string;
  grade: string;
  school: string;
  enrollment_status: string;
  parents: ParentBlock[];
  classes: ClassBlock[];
  orders: OrderBlock[];
  notifications: NotificationBlock[];
  /** PATCH 응답에만 실린다 — 다시 만들어졌을 때의 임시 비밀번호. */
  initial_password?: string | null;
  parent_initial_password?: string | null;
}

interface Form {
  name: string;
  school: string;
  grade: string;
  phone: string;
  parent_phone: string;
}

function toForm(detail: StudentDetail): Form {
  return {
    name: detail.name ?? "",
    school: detail.school,
    grade: detail.grade,
    phone: detail.phone,
    parent_phone: detail.parents[0]?.phone ?? "",
  };
}

/** 손댄 칸만 골라 낸다 — 서버는 온 필드만 고친다. */
function changed(form: Form, base: Form): Partial<Form> {
  const body: Partial<Form> = {};
  for (const key of Object.keys(form) as (keyof Form)[]) {
    if (form[key] !== base[key]) body[key] = form[key];
  }
  return body;
}

function day(value: string | null): string {
  return value ? value.slice(0, 10) : "—";
}

export default function StudentDetailPage() {
  const { studentId } = useParams();
  const detail = useApi(
    () => http.get<StudentDetail>(`/admin/students/${studentId}`).then((r) => r.data),
    [studentId],
  );

  const [form, setForm] = useState<Form | null>(null);
  const [base, setBase] = useState<Form | null>(null);
  const [issued, setIssued] = useState<StudentDetail | null>(null);

  useEffect(() => {
    if (!detail.data) return;
    setForm(toForm(detail.data));
    setBase(toForm(detail.data));
  }, [detail.data]);

  const save = useApiAction(async (body: Partial<Form>) => {
    const { data } = await http.patch<StudentDetail>(`/admin/students/${studentId}`, body);
    return data;
  });

  if (detail.initialLoading || !form || !base) return <Loading label="학생을 불러오는 중…" />;
  if (detail.error || !detail.data) {
    return <ErrorState description={detail.error ?? undefined} onRetry={detail.reload} />;
  }

  const data = detail.data;
  const body = changed(form, base);
  const dirty = Object.keys(body).length > 0;

  // 발송 내역의 어느 줄이든 다시 보낸다(FLOW 3-11) — 끝난 행은 새 행이 되고
  // 아직 안 끝난 행은 그 행이 다시 뜬다(서버 notification_admin.resend).
  const resend = useApiAction(async (notifId: number) => {
    await http.post(`/admin/notifications/${notifId}/resend`);
    return true;
  });

  const submit = async () => {
    setIssued(null);
    const updated = await save.run(body);
    if (!updated) return;
    detail.setData(updated);
    setIssued(updated);
  };

  const set = (key: keyof Form) => (event: { target: { value: string } }) =>
    setForm({ ...form, [key]: event.target.value });

  return (
    <div className="ui-stack">
      {save.error && (
        <Alert tone="danger" onClose={save.clearError}>
          {save.error}
        </Alert>
      )}
      {issued && (
        <Alert tone="success" onClose={() => setIssued(null)}>
          저장했습니다
          {issued.initial_password
            ? ` — 학생 아이디 ${issued.login_id} 비밀번호 ${issued.initial_password}`
            : ""}
          {issued.parent_initial_password
            ? ` — 학부모 아이디 ${issued.parents[0]?.login_id ?? ""} 비밀번호 ${issued.parent_initial_password}`
            : ""}
        </Alert>
      )}

      <Card
        title={data.name ?? data.matching_key}
        aside={<StatusBadge status={data.enrollment_status} />}
      >
        <div className="ui-stack ui-stack--md">
          <dl className="pm-stats">
            <div>
              <dt>아이디</dt>
              <dd>{data.login_id ?? "—"}</dd>
            </div>
            <div>
              <dt>대조키</dt>
              <dd>{data.matching_key}</dd>
            </div>
          </dl>

          <div className="ui-grid">
            <Field label="이름">
              {(props) => <Input {...props} value={form.name} onChange={set("name")} />}
            </Field>
            <Field label="학교">
              {(props) => <Input {...props} value={form.school} onChange={set("school")} />}
            </Field>
            <Field label="학년">
              {(props) => <Input {...props} value={form.grade} onChange={set("grade")} />}
            </Field>
            <Field label="학생 번호">
              {(props) => (
                <Input {...props} value={form.phone} onChange={set("phone")} inputMode="tel" />
              )}
            </Field>
            <Field label="학부모 번호">
              {(props) => (
                <Input
                  {...props}
                  value={form.parent_phone}
                  onChange={set("parent_phone")}
                  inputMode="tel"
                />
              )}
            </Field>
          </div>

          <div className="ui-row">
            <Button onClick={() => void submit()} loading={save.pending} disabled={!dirty}>
              저장
            </Button>
            {dirty && (
              <Button variant="ghost" onClick={() => setForm(base)}>
                되돌리기
              </Button>
            )}
          </div>
        </div>
      </Card>

      <Card title="듣는 반" padding="none">
        <Table<ClassBlock>
          rows={data.classes}
          rowKey={(row) => `${row.class_id}-${row.course_name}`}
          dense
          empty={<EmptyState title="수강 중인 반이 없습니다" />}
          columns={[
            { key: "class", header: "반", cell: (row) => row.class_name ?? "미배정" },
            { key: "course", header: "커리", cell: (row) => row.course_name },
            { key: "status", header: "상태", cell: (row) => <StatusBadge status={row.status} /> },
          ]}
        />
      </Card>

      <Card title="구입한 교재" padding="none">
        <Table<OrderBlock>
          rows={data.orders}
          rowKey={(row) => row.order_id}
          dense
          empty={<EmptyState title="주문이 없습니다" />}
          columns={[
            { key: "product", header: "교재", cell: (row) => row.product_name },
            {
              key: "amount",
              header: "금액",
              align: "right",
              cell: (row) => <span className="num">{row.amount.toLocaleString()}원</span>,
            },
            { key: "status", header: "상태", cell: (row) => <StatusBadge status={row.status} /> },
            {
              key: "billed_to_phone",
              header: "청구 번호",
              cell: (row) =>
                row.billed_to_phone || <span className="pm-none">—</span>,
            },
            { key: "ordered_at", header: "청구", cell: (row) => day(row.ordered_at) },
            { key: "paid_at", header: "결제", cell: (row) => day(row.paid_at) },
          ]}
        />
      </Card>

      <Card title="발송 내역" padding="none">
        <Table<NotificationBlock>
          rows={data.notifications}
          rowKey={(row) => row.notif_id}
          dense
          empty={<EmptyState title="발송 내역이 없습니다" />}
          columns={[
            { key: "type", header: "유형", cell: (row) => row.type },
            { key: "target", header: "받는 사람", cell: (row) => row.target?.kind ?? "—" },
            {
              key: "sent_to_phone",
              header: "보낸 번호",
              cell: (row) => row.sent_to_phone || <span className="pm-none">—</span>,
            },
            { key: "channel", header: "채널", cell: (row) => row.channel },
            {
              key: "status",
              header: "상태",
              cell: (row) => <StatusBadge status={row.status} />,
            },
            {
              key: "error_msg",
              header: "사유",
              cell: (row) => row.error_msg || <span className="pm-none">—</span>,
            },
            {
              key: "created_at",
              header: "시각",
              cell: (row) => day(row.sent_at ?? row.created_at),
            },
            {
              key: "resend",
              header: "",
              cell: (row) => (
                <Button
                  variant="ghost"
                  size="sm"
                  loading={resend.pending}
                  onClick={async () => {
                    if (await resend.run(row.notif_id)) await detail.reload();
                  }}
                >
                  다시 보내기
                </Button>
              ),
            },
          ]}
        />
      </Card>
    </div>
  );
}

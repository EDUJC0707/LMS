/**
 * /admin/staff — 직원 권한 매트릭스 (대표 전용).
 *
 * API
 *   GET   /api/admin/staff                      매트릭스(기능 키·직원별 프리셋/delta/유효)
 *   PUT   /api/admin/staff/{user_id}/features   변경분만 {기능키: bool}
 *   POST  /api/admin/staff                      직원 생성(이름·전화=아이디·역할)
 *   PATCH /api/admin/staff/{user_id}/deactivate 비활성(로그인 차단)
 *   PATCH /api/admin/staff/{user_id}/activate   재활성(로그인 허용, 멱등)
 *
 * 화면 설계
 * - 행=기능(12개 고정), 열=직원. 기능 수는 고정이고 직원 수만 늘어나므로
 *   이 방향이라야 데스크탑에서 가로 스크롤 없이 읽힌다.
 * - 셀은 프리셋 / 개별 부여 / 개별 회수 3축이 색·라벨로 갈린다(범례 참조).
 * - 서버가 400 을 주는 대상(자기 자신·대표)은 애초에 매트릭스에 넣지 않는다.
 * - 비활성은 되돌릴 수 있다. 기능 권한 delta 는 비활성 중에도 보존되므로
 *   재활성하면 원래 권한이 그대로 살아난다 — 계정을 새로 발급할 이유가 없다.
 */
import { FormEvent, useMemo, useState } from "react";

import { http, useApi, useApiAction } from "../../../api";
import { useMe } from "../../../auth";
import {
  Alert,
  Badge,
  Button,
  Card,
  DetailsPanel,
  ErrorState,
  Field,
  Input,
  Loading,
  Modal,
  PageHeader,
  Select,
  Table,
} from "../../../components";
import "./manage.css";
import type { StaffCreated, StaffMatrix, StaffRow } from "./types";

/** 기능 키가 실제로 무엇을 여는지 — backend/apps/accounts/features.py 주석 기준. */
const FEATURE_NOTE: Record<string, string> = {
  성적처리: "OMR 채점·보정과 성적표 배부",
  출결입력: "회차 출결 입력과 퇴원 처리",
  영상지급관리: "영상 업로드와 시청 권한 지급·회수",
  클리닉배정: "클리닉 승인·배정·출결·평가",
  결제확인: "결제 내역과 배부 상태 확인",
  공지작성: "공지·주차 공지 게시",
  상담기록: "결석·학부모 상담 기록",
  알림발송: "알림 발송과 발송 내역 조회",
  워크북업로드: "워크북 사진 업로드와 학생 매칭",
  문제은행관리: "문제은행·유사문항 관리",
  계정관리: "명단 입력·계정 발급·등록 전환",
  권한부여: "직원 권한 조정",
};

type DirtyMap = Record<number, Record<string, boolean>>;
type Origin = "preset" | "added" | "removed" | "none";

const ORIGIN_LABEL: Record<Origin, string> = {
  preset: "프리셋",
  added: "개별 부여",
  removed: "개별 회수",
  none: "미부여",
};

const ORIGIN_MARK: Record<Origin, string> = {
  preset: "✓",
  added: "＋",
  removed: "－",
  none: "·",
};

function originOf(on: boolean, inPreset: boolean): Origin {
  if (on) return inPreset ? "preset" : "added";
  return inPreset ? "removed" : "none";
}

export default function StaffPage() {
  const { me } = useMe();
  const matrix = useApi(() => http.get<StaffMatrix>("/admin/staff").then((r) => r.data), []);

  const [dirty, setDirty] = useState<DirtyMap>({});
  const [savingId, setSavingId] = useState<number | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [issued, setIssued] = useState<StaffCreated | null>(null);
  const [deactivating, setDeactivating] = useState<StaffRow | null>(null);

  // useApiAction 은 실패하면 undefined 를 돌려준다 — 성공을 구분하려면
  // 액션이 값을 반환해야 한다(void 를 반환하면 성공도 undefined 가 된다).
  const save = useApiAction(async (staff: StaffRow, changes: Record<string, boolean>) => {
    await http.put(`/admin/staff/${staff.user_id}/features`, changes);
    return true;
  });
  const deactivate = useApiAction(async (userId: number) => {
    await http.patch(`/admin/staff/${userId}/deactivate`);
    return true;
  });
  const activate = useApiAction(async (userId: number) => {
    await http.patch(`/admin/staff/${userId}/activate`);
    return true;
  });
  const [activatingId, setActivatingId] = useState<number | null>(null);

  const data = matrix.data;

  // 서버가 400 을 돌려주는 대상은 화면에 아예 두지 않는다(자기 자신·대표).
  const editable = useMemo(
    () => (data?.staff ?? []).filter((s) => s.user_id !== me?.user_id && s.role !== "대표"),
    [data, me],
  );
  const active = editable.filter((s) => s.is_active);
  const retired = editable.filter((s) => !s.is_active);

  const savedOn = (staff: StaffRow, key: string) => staff.effective.includes(key);
  const currentOn = (staff: StaffRow, key: string) =>
    dirty[staff.user_id]?.[key] ?? savedOn(staff, key);

  /** 저장 대상 = 지금 값이 서버 값과 다른 항목만. */
  const changesOf = (staff: StaffRow): Record<string, boolean> => {
    const pending = dirty[staff.user_id] ?? {};
    const out: Record<string, boolean> = {};
    for (const [key, value] of Object.entries(pending)) {
      if (value !== savedOn(staff, key)) out[key] = value;
    }
    return out;
  };

  const toggle = (staff: StaffRow, key: string) =>
    setDirty((prev) => ({
      ...prev,
      [staff.user_id]: { ...prev[staff.user_id], [key]: !currentOn(staff, key) },
    }));

  const revert = (staff: StaffRow) =>
    setDirty((prev) => {
      const next = { ...prev };
      delete next[staff.user_id];
      return next;
    });

  const commit = async (staff: StaffRow) => {
    const changes = changesOf(staff);
    if (Object.keys(changes).length === 0) return;
    setSavingId(staff.user_id);
    const ok = await save.run(staff, changes);
    setSavingId(null);
    if (!ok) return; // 실패 사유는 매트릭스 위 Alert 로 보인다
    revert(staff);
    await matrix.reload();
  };

  const confirmDeactivate = async () => {
    if (!deactivating) return;
    const ok = await deactivate.run(deactivating.user_id);
    if (!ok) return; // 실패 사유는 모달 안 Alert 로 보인다
    setDeactivating(null);
    await matrix.reload();
  };

  const restore = async (staff: StaffRow) => {
    setActivatingId(staff.user_id);
    const ok = await activate.run(staff.user_id);
    setActivatingId(null);
    if (!ok) return; // 실패 사유는 비활성 목록 위 Alert 로 보인다
    await matrix.reload();
  };

  return (
    <>
      <PageHeader
        title="직원 권한"
        actions={
          <Button variant="primary" onClick={() => setCreateOpen(true)}>
            직원 계정 만들기
          </Button>
        }
      />

      {issued && (
        <Alert tone="success" onClose={() => setIssued(null)}>
          {issued.name}({issued.role}) 계정을 만들었습니다. 아이디{" "}
          <span className="num">{issued.login_id}</span> · 초기 비밀번호{" "}
          <span className="pm-secret">{issued.initial_password}</span>
        </Alert>
      )}

      {save.error && (
        <Alert tone="danger" onClose={save.clearError}>
          {save.error}
        </Alert>
      )}

      {matrix.loading ? (
        <Loading label="직원 권한을 불러오는 중…" />
      ) : matrix.error ? (
        <ErrorState description={matrix.error} onRetry={matrix.reload} />
      ) : !data ? null : (
        <>
          <Card
            title="권한 매트릭스"
            aside={`재직 직원 ${active.length}명 · 기능 ${data.feature_keys.length}개`}
            padding="none"
          >
            {active.length === 0 ? (
              <div style={{ padding: "var(--space-lg)" }}>
                <Alert tone="info">아직 관리자·조교 계정이 없습니다</Alert>
              </div>
            ) : (
              <div className="ui-tablewrap">
                <table className="pm-matrix">
                  <caption className="sr-only">기능별 직원 권한 매트릭스</caption>
                  <thead>
                    <tr>
                      <th scope="col" className="pm-matrix__feature">
                        기능
                      </th>
                      {active.map((staff) => {
                        const count = Object.keys(changesOf(staff)).length;
                        return (
                          <th key={staff.user_id} scope="col">
                            <span className="pm-staffhead">
                              <span className="pm-staffhead__name">
                                {staff.name}{" "}
                                <Badge tone={staff.role === "관리자" ? "accent" : "neutral"}>
                                  {staff.role}
                                </Badge>
                              </span>
                              <span className="pm-staffhead__id num">{staff.login_id}</span>
                              <span className="pm-staffhead__actions">
                                {count > 0 ? (
                                  <>
                                    <Button
                                      size="sm"
                                      variant="primary"
                                      loading={savingId === staff.user_id}
                                      onClick={() => void commit(staff)}
                                    >
                                      {count}건 저장
                                    </Button>
                                    <Button size="sm" variant="ghost" onClick={() => revert(staff)}>
                                      되돌리기
                                    </Button>
                                  </>
                                ) : (
                                  <Button
                                    size="sm"
                                    variant="ghost"
                                    onClick={() => setDeactivating(staff)}
                                  >
                                    로그인 막기
                                  </Button>
                                )}
                              </span>
                            </span>
                          </th>
                        );
                      })}
                    </tr>
                  </thead>
                  <tbody>
                    {data.feature_keys.map((key) => (
                      <tr key={key}>
                        <th scope="row" className="pm-matrix__feature">
                          <b>{key}</b>
                          <span>{FEATURE_NOTE[key] ?? "이 학원에서 쓰는 추가 기능입니다."}</span>
                        </th>
                        {active.map((staff) => {
                          const on = currentOn(staff, key);
                          const origin = originOf(on, staff.preset.includes(key));
                          const changed = on !== savedOn(staff, key);
                          return (
                            <td key={staff.user_id}>
                              <button
                                type="button"
                                role="switch"
                                aria-checked={on}
                                className="pm-grant"
                                data-origin={origin}
                                data-changed={changed}
                                onClick={() => toggle(staff, key)}
                                aria-label={`${staff.name} · ${key} — 현재 ${ORIGIN_LABEL[origin]}`}
                              >
                                <span className="pm-grant__mark" aria-hidden="true">
                                  {ORIGIN_MARK[origin]}
                                </span>
                                {ORIGIN_LABEL[origin]}
                                {changed && " · 저장 전"}
                              </button>
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          <Card title="매트릭스 읽는 법" flat padding="sm">
            <p className="pm-legend">
              <span className="pm-grant" data-origin="preset">
                <span className="pm-grant__mark" aria-hidden="true">
                  ✓
                </span>
                프리셋
              </span>
              역할을 주면 자동으로 따라오는 기본 권한
              <span className="pm-grant" data-origin="added">
                <span className="pm-grant__mark" aria-hidden="true">
                  ＋
                </span>
                개별 부여
              </span>
              이 사람에게만 따로 열어 준 것
              <span className="pm-grant" data-origin="removed">
                <span className="pm-grant__mark" aria-hidden="true">
                  －
                </span>
                개별 회수
              </span>
              프리셋에는 있지만 이 사람에게는 닫은 것
              <span className="pm-grant" data-origin="none">
                <span className="pm-grant__mark" aria-hidden="true">
                  ·
                </span>
                미부여
              </span>
              프리셋에도 없고 따로 주지도 않은 것
            </p>
          </Card>

          {retired.length > 0 && (
            <DetailsPanel
              summary="비활성 직원"
              aside={`${retired.length}명 — 로그인 차단됨`}
              defaultOpen
            >
              {activate.error && (
                <Alert tone="danger" onClose={activate.clearError}>
                  {activate.error}
                </Alert>
              )}

              <Table<StaffRow>
                rows={retired}
                rowKey={(row) => row.user_id}
                dense
                caption="비활성 직원과 재활성 처리"
                columns={[
                  { key: "name", header: "이름", cell: (row) => row.name },
                  {
                    key: "role",
                    header: "역할",
                    width: "6rem",
                    cell: (row) => (
                      <Badge tone={row.role === "관리자" ? "accent" : "neutral"}>{row.role}</Badge>
                    ),
                  },
                  {
                    key: "login_id",
                    header: "아이디",
                    numeric: true,
                    cell: (row) => row.login_id,
                  },
                  {
                    key: "state",
                    header: "상태",
                    width: "8rem",
                    cell: () => <Badge tone="warning">로그인 차단</Badge>,
                  },
                  {
                    key: "features",
                    header: "보존된 권한",
                    cell: (row) =>
                      row.effective.length === 0 ? (
                        <span style={{ color: "var(--color-muted)" }}>없음</span>
                      ) : (
                        `${row.effective.length}개 — ${row.effective.join(" · ")}`
                      ),
                  },
                  {
                    key: "action",
                    header: "처리",
                    align: "right",
                    width: "9rem",
                    cell: (row) => (
                      <Button
                        size="sm"
                        variant="primary"
                        loading={activatingId === row.user_id}
                        onClick={() => void restore(row)}
                      >
                        다시 활성화
                      </Button>
                    ),
                  },
                ]}
              />
            </DetailsPanel>
          )}
        </>
      )}

      <CreateStaffModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={(row) => {
          setIssued(row);
          setCreateOpen(false);
          void matrix.reload();
        }}
      />

      <Modal
        open={deactivating !== null}
        onClose={() => setDeactivating(null)}
        title="이 직원의 로그인을 막을까요?"
        footer={
          <>
            <Button onClick={() => setDeactivating(null)}>그대로 두기</Button>
            <Button
              variant="danger"
              loading={deactivate.pending}
              onClick={() => void confirmDeactivate()}
            >
              비활성 처리
            </Button>
          </>
        }
      >
        {deactivate.error && <Alert tone="danger">{deactivate.error}</Alert>}
        <p style={{ margin: 0 }}>
          {deactivating?.name}({deactivating?.role}) 계정이 로그인할 수 없게 됩니다.
        </p>
      </Modal>
    </>
  );
}

/* ── 직원 계정 생성 ─────────────────────────────────────────────────── */

function CreateStaffModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (row: StaffCreated) => void;
}) {
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [role, setRole] = useState("관리자");
  const [touched, setTouched] = useState<{ name?: boolean; phone?: boolean }>({});

  const create = useApiAction(async (body: { name: string; phone: string; role: string }) => {
    const { data } = await http.post<StaffCreated>("/admin/staff", body);
    return data;
  });

  const nameError = touched.name && !name.trim() ? "이름을 적어 주세요." : null;
  const phoneError =
    touched.phone && !phone.trim() ? "휴대폰 번호가 곧 로그인 아이디입니다." : null;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setTouched({ name: true, phone: true });
    if (!name.trim() || !phone.trim()) return;
    const row = await create.run({ name: name.trim(), phone: phone.trim(), role });
    if (!row) return;
    setName("");
    setPhone("");
    setTouched({});
    onCreated(row);
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="직원 계정 만들기"
      footer={
        <>
          <Button onClick={onClose}>취소</Button>
          <Button variant="primary" type="submit" form="staff-create" loading={create.pending}>
            계정 발급
          </Button>
        </>
      }
    >
      <form id="staff-create" onSubmit={submit} className="ui-stack--md">
        {create.error && <Alert tone="danger">{create.error}</Alert>}
        <Field label="이름" required error={nameError}>
          {(props) => (
            <Input
              {...props}
              value={name}
              onChange={(e) => setName(e.target.value)}
              onBlur={() => setTouched((t) => ({ ...t, name: true }))}
              autoComplete="off"
            />
          )}
        </Field>
        <Field
          label="휴대폰 번호"
          required
          error={phoneError}
        >
          {(props) => (
            <Input
              {...props}
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              onBlur={() => setTouched((t) => ({ ...t, phone: true }))}
              placeholder="01012345678"
              inputMode="numeric"
              autoComplete="off"
            />
          )}
        </Field>
        <Field
          label="역할"
        >
          {(props) => (
            <Select {...props} value={role} onChange={(e) => setRole(e.target.value)}>
              <option value="관리자">관리자</option>
              <option value="조교">조교</option>
            </Select>
          )}
        </Field>
      </form>
    </Modal>
  );
}

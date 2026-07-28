/**
 * /admin/workbook — 워크북 사진 업로드 · 학생 매칭.
 *
 * API
 *   POST   /api/admin/workbook/upload         멀티파트 images[] + student_id (+session_id)
 *   GET    /api/admin/workbook?status=&session_id=
 *   PATCH  /api/admin/workbook/{id}/match     {student_id} 또는 {recognized_unique_id,recognized_name}
 *   DELETE /api/admin/workbook/{id}
 *   GET    /api/admin/attendance/sessions(/{id})  회차·학생 명단(출결입력 권한이 있을 때만)
 *
 * 화면 설계
 * - 매칭은 “사진을 보고 사람을 고르는” 일이라 표가 아니라 썸네일 격자다.
 *   보정이 필요한 건(대기·불일치·인식실패)은 테두리로 먼저 눈에 띈다.
 * - 학생 목록을 주는 API 가 따로 없다. 출결 권한이 있으면 회차 출석부에서
 *   명단을 빌려 오고, 없으면 이미 올라온 사진들에 붙은 학생으로 목록을 만든다
 *   — 어느 쪽이든 서버가 실제로 내려준 학생만 고를 수 있다.
 */
import { useEffect, useMemo, useState } from "react";

import { http, mediaUrl, useApi, useApiAction } from "../../../api";
import { useMe } from "../../../auth";
import {
  Alert,
  Badge,
  Button,
  Card,
  DetailsPanel,
  EmptyState,
  ErrorState,
  Field,
  Input,
  Loading,
  Modal,
  PageHeader,
  Select,
  StatusBadge,
  Tabs,
} from "../../../components";
import "./manage.css";
import type { SessionDetail, SessionRow, WorkbookList, WorkbookRow } from "./types";

type StatusTab = "전체" | "대기" | "자동매칭" | "수동확정" | "불일치" | "인식실패";
const STATUS_TABS: { key: StatusTab; label: string }[] = [
  { key: "전체", label: "전체" },
  { key: "대기", label: "대조 전" },
  { key: "불일치", label: "불일치" },
  { key: "인식실패", label: "인식 실패" },
  { key: "자동매칭", label: "자동 매칭" },
  { key: "수동확정", label: "수동 확정" },
];

interface StudentOption {
  student_id: number;
  name: string;
  unique_id: string;
}

/** 보정이 남은 건 — 서버의 미매핑 정의(대기·불일치·인식실패)와 같다. */
function needsAttention(row: WorkbookRow): boolean {
  return row.match_status === null || row.match_status === "불일치" || row.match_status === "인식실패";
}

export default function WorkbookManagePage() {
  const { hasFeature } = useMe();
  const canReadSessions = hasFeature("출결입력");

  const [tab, setTab] = useState<StatusTab>("전체");
  const [sessionFilter, setSessionFilter] = useState<string>("");

  const list = useApi(async () => {
    const { data } = await http.get<WorkbookList>("/admin/workbook", {
      params: {
        ...(tab === "전체" ? {} : { status: tab }),
        ...(sessionFilter ? { session_id: sessionFilter } : {}),
      },
    });
    return data;
  }, [tab, sessionFilter]);

  const sessions = useApi(async () => {
    if (!canReadSessions) return null;
    const { data } = await http.get<{ sessions: SessionRow[] }>("/admin/attendance/sessions");
    return data.sessions;
  }, [canReadSessions]);

  // 명단을 빌려 올 회차 — 필터를 걸었으면 그 회차, 아니면 가장 최근 회차.
  const rosterSessionId = useMemo(() => {
    if (sessionFilter) return Number(sessionFilter);
    const all = sessions.data ?? [];
    return all.length > 0 ? all[all.length - 1].session_id : null;
  }, [sessionFilter, sessions.data]);

  const roster = useApi(async () => {
    if (!canReadSessions || rosterSessionId === null) return null;
    const { data } = await http.get<SessionDetail>(`/admin/attendance/sessions/${rosterSessionId}`);
    return data.students;
  }, [canReadSessions, rosterSessionId]);

  /** 고를 수 있는 학생 = 출석부 명단 ∪ 이미 올라온 사진에 붙은 학생. */
  const studentOptions: StudentOption[] = useMemo(() => {
    const map = new Map<number, StudentOption>();
    for (const student of roster.data ?? []) {
      map.set(student.student_id, {
        student_id: student.student_id,
        name: student.name,
        unique_id: student.unique_id,
      });
    }
    for (const row of list.data?.submissions ?? []) {
      if (!map.has(row.student.student_id)) {
        map.set(row.student.student_id, {
          student_id: row.student.student_id,
          name: row.student.name ?? "이름 미등록",
          unique_id: row.student.unique_id,
        });
      }
    }
    return [...map.values()].sort((a, b) => a.unique_id.localeCompare(b.unique_id, "ko"));
  }, [roster.data, list.data]);

  const [deleting, setDeleting] = useState<WorkbookRow | null>(null);
  const remove = useApiAction(async (submissionId: number) => {
    await http.delete(`/admin/workbook/${submissionId}`);
    return true;
  });

  const submissions = list.data?.submissions ?? [];

  return (
    <>
      <PageHeader
        title="워크북 업로드"
        description="수업 끝에 걷은 워크북 마지막 장을 올리고, 사진마다 어느 학생 것인지 확정합니다. 확정된 사진만 학생·학부모에게 보입니다."
      />

      <UploadCard
        students={studentOptions}
        sessions={sessions.data ?? []}
        onUploaded={() => void list.reload()}
      />

      <Card
        title="매칭 보드"
        aside={
          list.data ? (
            list.data.unmatched_count > 0 ? (
              <>
                <Badge tone="warning">보정 필요 {list.data.unmatched_count}장</Badge>{" "}
                <span style={{ color: "var(--color-muted)" }}>전체 {list.data.total_count}장</span>
              </>
            ) : (
              <>전체 {list.data.total_count}장 — 모두 확정됐습니다</>
            )
          ) : undefined
        }
      >
        <div className="ui-stack--md">
          <Tabs items={STATUS_TABS} value={tab} onChange={setTab} label="매칭 상태" />

          {sessions.data && sessions.data.length > 0 && (
            <div className="pm-toolbar">
              <Field label="회차">
                {(props) => (
                  <Select
                    {...props}
                    value={sessionFilter}
                    onChange={(e) => setSessionFilter(e.target.value)}
                  >
                    <option value="">모든 회차</option>
                    {sessions.data?.map((session) => (
                      <option key={session.session_id} value={session.session_id}>
                        {session.session_date}
                        {session.session_no ? ` · ${session.session_no}회차` : ""}
                      </option>
                    ))}
                  </Select>
                )}
              </Field>
              {sessionFilter && (
                <Button variant="ghost" onClick={() => setSessionFilter("")}>
                  회차 조건 지우기
                </Button>
              )}
            </div>
          )}

          {remove.error && (
            <Alert tone="danger" onClose={remove.clearError}>
              {remove.error}
            </Alert>
          )}

          {list.loading ? (
            <Loading label="올라온 사진을 불러오는 중…" />
          ) : list.error ? (
            <ErrorState description={list.error} onRetry={list.reload} />
          ) : submissions.length === 0 ? (
            <EmptyState
              title={
                tab === "전체"
                  ? "이 조건에 올라온 사진이 없습니다"
                  : `${tab} 상태인 사진이 없습니다`
              }
              description="위에서 사진을 올리거나, 상태 탭·회차 조건을 바꿔 보세요."
            />
          ) : (
            <ul className="pm-wbgrid">
              {submissions.map((row) => (
                <MatchCard
                  key={row.submission_id}
                  row={row}
                  students={studentOptions}
                  onDone={() => void list.reload()}
                  onDelete={() => setDeleting(row)}
                />
              ))}
            </ul>
          )}
        </div>
      </Card>

      <Modal
        open={deleting !== null}
        onClose={() => setDeleting(null)}
        title="이 사진을 지울까요?"
        footer={
          <>
            <Button onClick={() => setDeleting(null)}>그대로 두기</Button>
            <Button
              variant="danger"
              loading={remove.pending}
              onClick={async () => {
                if (!deleting) return;
                if (!(await remove.run(deleting.submission_id))) return;
                setDeleting(null);
                await list.reload();
              }}
            >
              사진 삭제
            </Button>
          </>
        }
      >
        <p style={{ marginTop: 0 }}>
          사진 파일까지 함께 지워지고 되돌릴 수 없습니다. 잘못 찍혔거나 같은 장을 두 번 올린
          경우에만 지우세요.
        </p>
        <p style={{ marginBottom: 0, color: "var(--color-muted)" }}>
          내가 올린 사진이 아니면 관리자·대표만 지울 수 있습니다.
        </p>
      </Modal>
    </>
  );
}

/* ── 업로드 ─────────────────────────────────────────────────────────── */

function UploadCard({
  students,
  sessions,
  onUploaded,
}: {
  students: StudentOption[];
  sessions: SessionRow[];
  onUploaded: () => void;
}) {
  const [files, setFiles] = useState<File[]>([]);
  const [previews, setPreviews] = useState<string[]>([]);
  const [studentId, setStudentId] = useState("");
  const [sessionId, setSessionId] = useState("");
  const [over, setOver] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  // 미리보기 URL 은 파일이 바뀔 때마다 새로 만들고 이전 것은 반드시 해제한다.
  useEffect(() => {
    const urls = files.map((file) => URL.createObjectURL(file));
    setPreviews(urls);
    return () => urls.forEach((url) => URL.revokeObjectURL(url));
  }, [files]);

  const upload = useApiAction(async (form: FormData) => {
    const { data } = await http.post<{ submissions: WorkbookRow[] }>(
      "/admin/workbook/upload",
      form,
      { headers: { "Content-Type": "multipart/form-data" } },
    );
    return data.submissions.length;
  });

  const accept = (incoming: FileList | null) => {
    if (!incoming || incoming.length === 0) return;
    const picked = Array.from(incoming).filter((file) =>
      /\.(jpe?g|png|webp)$/i.test(file.name),
    );
    if (picked.length === 0) {
      setLocalError("jpg·png·webp 사진만 올릴 수 있습니다.");
      return;
    }
    const tooBig = picked.find((file) => file.size > 10 * 1024 * 1024);
    if (tooBig) {
      setLocalError(`${tooBig.name} 은 10MB 를 넘습니다. 장당 10MB 이하로 줄여 주세요.`);
      return;
    }
    setLocalError(null);
    setFiles((prev) => [...prev, ...picked]);
  };

  const submit = async () => {
    if (files.length === 0) {
      setLocalError("올릴 사진을 먼저 고르세요.");
      return;
    }
    if (!studentId) {
      setLocalError("이 사진이 누구 것인지 먼저 고르세요.");
      return;
    }
    setLocalError(null);
    const form = new FormData();
    for (const file of files) form.append("images", file);
    form.append("student_id", studentId);
    if (sessionId) form.append("session_id", sessionId);
    const count = await upload.run(form);
    if (count === undefined) return;
    setFiles([]);
    onUploaded();
  };

  return (
    <Card
      title="사진 올리기"
      aside={files.length > 0 ? `${files.length}장 대기 중` : undefined}
    >
      <div className="ui-stack--md">
        {(localError || upload.error) && (
          <Alert tone="danger" onClose={() => setLocalError(null)}>
            {localError ?? upload.error}
          </Alert>
        )}

        <label
          className="pm-drop"
          data-over={over}
          onDragOver={(event) => {
            event.preventDefault();
            setOver(true);
          }}
          onDragLeave={() => setOver(false)}
          onDrop={(event) => {
            event.preventDefault();
            setOver(false);
            accept(event.dataTransfer.files);
          }}
        >
          <input
            type="file"
            className="sr-only"
            multiple
            accept=".jpg,.jpeg,.png,.webp"
            onChange={(event) => {
              accept(event.target.files);
              event.target.value = "";
            }}
          />
          <b>사진을 여기에 끌어다 놓으세요</b>
          <span>누르면 파일을 골라 올릴 수도 있습니다 · jpg·png·webp, 장당 10MB 이하</span>
        </label>

        {previews.length > 0 && (
          <ul className="pm-queue">
            {previews.map((url, index) => (
              <li key={url}>
                <figure style={{ margin: 0 }}>
                  <img src={url} alt="" />
                  <figcaption>{files[index]?.name}</figcaption>
                </figure>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setFiles((prev) => prev.filter((_, i) => i !== index))}
                  aria-label={`${files[index]?.name} 빼기`}
                >
                  빼기
                </Button>
              </li>
            ))}
          </ul>
        )}

        <div className="pm-toolbar">
          <Field
            label="학생"
            required
            hint={
              students.length === 0
                ? "고를 수 있는 학생이 아직 없습니다. 출결 회차가 만들어지면 명단이 채워집니다."
                : "먼저 잠정으로 지정하고, 아래 매칭 보드에서 확정합니다."
            }
          >
            {(props) => (
              <Select
                {...props}
                value={studentId}
                onChange={(e) => setStudentId(e.target.value)}
                disabled={students.length === 0}
              >
                <option value="">학생 고르기</option>
                {students.map((student) => (
                  <option key={student.student_id} value={student.student_id}>
                    {student.unique_id} · {student.name}
                  </option>
                ))}
              </Select>
            )}
          </Field>

          {sessions.length > 0 && (
            <Field label="회차" hint="비워 두면 회차 없이 저장됩니다.">
              {(props) => (
                <Select
                  {...props}
                  value={sessionId}
                  onChange={(e) => setSessionId(e.target.value)}
                >
                  <option value="">회차 지정 안 함</option>
                  {sessions.map((session) => (
                    <option key={session.session_id} value={session.session_id}>
                      {session.session_date}
                      {session.session_no ? ` · ${session.session_no}회차` : ""}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
          )}

          <div className="pm-toolbar__end">
            <Button variant="primary" loading={upload.pending} onClick={() => void submit()}>
              {files.length > 0 ? `${files.length}장 올리기` : "올리기"}
            </Button>
          </div>
        </div>
      </div>
    </Card>
  );
}

/* ── 사진 한 장의 매칭 ──────────────────────────────────────────────── */

function MatchCard({
  row,
  students,
  onDone,
  onDelete,
}: {
  row: WorkbookRow;
  students: StudentOption[];
  onDone: () => void;
  onDelete: () => void;
}) {
  const [manualId, setManualId] = useState(String(row.student.student_id));
  const [uniqueId, setUniqueId] = useState(row.recognized_unique_id ?? row.student.unique_id);
  const [name, setName] = useState(row.recognized_name ?? "");

  const match = useApiAction(
    async (body: Record<string, string | number>) => {
      await http.patch(`/admin/workbook/${row.submission_id}/match`, body);
      return true;
    },
  );

  const status = row.match_status ?? "대기";
  const attention = needsAttention(row);

  return (
    <li className="pm-wbitem" data-attention={attention}>
      <a
        className="pm-wbthumb"
        href={mediaUrl(row.image_url)}
        target="_blank"
        rel="noreferrer"
        aria-label={`${row.student.name ?? "학생"} 워크북 사진 크게 보기`}
      >
        <img src={mediaUrl(row.image_url)} alt={`${row.student.name ?? "학생"}의 워크북 사진`} />
      </a>

      <div className="pm-wbbody">
        <p className="pm-wbname">
          {row.student.name ?? "이름 미등록"}
          <small className="num">원번 {row.student.unique_id}</small>
        </p>

        <div className="ui-row">
          <StatusBadge status={status} />
          {row.performance_grade && <Badge tone="neutral">수행 {row.performance_grade}</Badge>}
          {row.session && (
            <Badge tone="outline">
              {row.session.session_date}
              {row.session.session_no ? ` · ${row.session.session_no}회차` : ""}
            </Badge>
          )}
        </div>

        <dl className="pm-defs">
          <dt>인식 원번</dt>
          <dd className="num">{row.recognized_unique_id ?? "아직 없음"}</dd>
          <dt>인식 이름</dt>
          <dd>{row.recognized_name ?? "아직 없음"}</dd>
          <dt>올린 사람</dt>
          <dd>{row.uploaded_by?.name ?? "기록 없음"}</dd>
        </dl>

        <DetailsPanel
          summary="누구 것인지 정하기"
          defaultOpen={attention}
          aside={attention ? "확정 필요" : undefined}
        >
          <div className="ui-stack--sm">
            {match.error && <Alert tone="danger">{match.error}</Alert>}

            <Field label="학생 직접 지정" hint="사진을 보고 바로 확정할 때.">
              {(props) => (
                <Select
                  {...props}
                  value={manualId}
                  onChange={(e) => setManualId(e.target.value)}
                  disabled={students.length === 0}
                >
                  {students.map((student) => (
                    <option key={student.student_id} value={student.student_id}>
                      {student.unique_id} · {student.name}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            <Button
              loading={match.pending}
              disabled={!manualId}
              onClick={async () => {
                if (await match.run({ student_id: Number(manualId) })) onDone();
              }}
            >
              이 학생으로 확정
            </Button>

            <hr
              style={{
                border: 0,
                borderTop: "1px solid var(--color-rule-2)",
                margin: "var(--space-xs) 0",
              }}
            />

            <Field
              label="사진에 적힌 원번"
              hint="원번과 이름이 정확히 한 명과 맞으면 자동으로 확정됩니다."
            >
              {(props) => (
                <Input
                  {...props}
                  value={uniqueId}
                  onChange={(e) => setUniqueId(e.target.value)}
                  placeholder="26001"
                  inputMode="numeric"
                />
              )}
            </Field>
            <Field label="사진에 적힌 이름">
              {(props) => (
                <Input
                  {...props}
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="김하늘"
                />
              )}
            </Field>
            <Button
              loading={match.pending}
              disabled={!uniqueId.trim()}
              onClick={async () => {
                const ok = await match.run({
                  recognized_unique_id: uniqueId.trim(),
                  recognized_name: name.trim(),
                });
                if (ok) onDone();
              }}
            >
              원번·이름으로 대조
            </Button>

            <Button variant="danger" size="sm" onClick={onDelete}>
              사진 삭제
            </Button>
          </div>
        </DetailsPanel>
      </div>
    </li>
  );
}

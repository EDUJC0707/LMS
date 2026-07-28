/**
 * /admin/workbook — 워크북 사진 업로드 · 학생 매칭.
 *
 * API
 *   POST   /api/admin/workbook/upload         멀티파트 images[] + student_id (+session_id)
 *   GET    /api/admin/workbook?status=&session_id=
 *   PATCH  /api/admin/workbook/{id}/match     {student_id} 또는 {recognized_unique_id,recognized_name}
 *   DELETE /api/admin/workbook/{id}
 *   GET    /api/admin/attendance/sessions        회차 목록(출결입력 권한이 있을 때만)
 *   GET    /api/admin/students?q=                학생 명부 검색(직원 공통 권한)
 *
 * 화면 설계
 * - 매칭은 “사진을 보고 사람을 고르는” 일이라 표가 아니라 썸네일 격자다.
 *   보정이 필요한 건(대기·불일치·인식실패)은 테두리로 먼저 눈에 띈다.
 * - 학생은 명부 API 로 이름·원번을 쳐서 고른다(StudentPicker). 예전에는 출결
 *   출석부에서 명단을 빌려 와야 해서 출결 권한이 없는 조교는 후보가 0명이었다.
 */
import { useEffect, useState } from "react";

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
  Select,
  StatusBadge,
  Tabs,
} from "../../../components";
import { StudentPicker } from "./StudentPicker";
import type { DirectoryStudent } from "./directory";
import "./manage.css";
import type { SessionRow, WorkbookList, WorkbookRow } from "./types";

type StatusTab = "전체" | "대기" | "자동매칭" | "수동확정" | "불일치" | "인식실패";
const STATUS_TABS: { key: StatusTab; label: string }[] = [
  { key: "전체", label: "전체" },
  { key: "대기", label: "대조 전" },
  { key: "불일치", label: "불일치" },
  { key: "인식실패", label: "인식 실패" },
  { key: "자동매칭", label: "자동 매칭" },
  { key: "수동확정", label: "수동 확정" },
];

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

  const [deleting, setDeleting] = useState<WorkbookRow | null>(null);
  const remove = useApiAction(async (submissionId: number) => {
    await http.delete(`/admin/workbook/${submissionId}`);
    return true;
  });

  const submissions = list.data?.submissions ?? [];

  return (
    <div className="ui-stack">
      <UploadCard sessions={sessions.data ?? []} onUploaded={() => void list.reload()} />

      <Card
        title="매칭 보드"
        aside={
          list.data ? (
            list.data.unmatched_count > 0 ? (
              <>
                <Badge tone="warning">보정 필요 {list.data.unmatched_count}장</Badge>{" "}
                <span className="pm-none">전체 {list.data.total_count}장</span>
              </>
            ) : (
              `전체 ${list.data.total_count}장`
            )
          ) : undefined
        }
      >
        <div className="ui-stack">
          {/* 상태 탭과 회차는 같은 일(보드 좁히기)을 한다 — 16px 으로 묶고
              보드와는 24px 로 띄운다. */}
          <div className="ui-stack ui-stack--md">
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
          </div>

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
            />
          ) : (
            <ul className="pm-wbgrid">
              {submissions.map((row) => (
                <MatchCard
                  key={row.submission_id}
                  row={row}
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
        <p style={{ margin: 0 }}>
          {deleting?.student.name ?? "미확정"}
          {deleting?.session ? ` · ${deleting.session.session_date}` : ""}
        </p>
      </Modal>
    </div>
  );
}

/* ── 업로드 ─────────────────────────────────────────────────────────── */

function UploadCard({
  sessions,
  onUploaded,
}: {
  sessions: SessionRow[];
  onUploaded: () => void;
}) {
  const [files, setFiles] = useState<File[]>([]);
  const [previews, setPreviews] = useState<string[]>([]);
  const [student, setStudent] = useState<DirectoryStudent | null>(null);
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
    if (!student) {
      setLocalError("이 사진이 누구 것인지 먼저 고르세요.");
      return;
    }
    setLocalError(null);
    const form = new FormData();
    for (const file of files) form.append("images", file);
    form.append("student_id", String(student.student_id));
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
      <div className="ui-stack ui-stack--md">
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
          {/* 남긴 건 제약뿐이다 — "누르면 파일을 고를 수도 있다"는 눌러 보면 안다. */}
          <span>jpg · png · webp · 장당 10MB 이하</span>
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
          <StudentPicker
            value={student}
            onChange={setStudent}
            required
          />

          {sessions.length > 0 && (
            <Field label="회차">
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
  onDone,
  onDelete,
}: {
  row: WorkbookRow;
  onDone: () => void;
  onDelete: () => void;
}) {
  const [picked, setPicked] = useState<DirectoryStudent | null>(null);
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
          {/* 확정하는 길이 둘이다(명부에서 고르기 · 사진에 적힌 값으로 대조).
              각 길을 8px 로 묶고 길끼리는 16px + 실선으로 가른다. */}
          <div className="ui-stack ui-stack--md">
            {match.error && <Alert tone="danger">{match.error}</Alert>}

            <div className="ui-stack ui-stack--sm">
              <StudentPicker value={picked} onChange={setPicked} label="학생 직접 지정" />
              <Button
                loading={match.pending}
                disabled={!picked}
                onClick={async () => {
                  if (!picked) return;
                  if (await match.run({ student_id: picked.student_id })) onDone();
                }}
              >
                이 학생으로 확정
              </Button>
            </div>

            <div className="ui-stack ui-stack--sm pm-actionblock">
              <Field label="사진에 적힌 원번">
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
                    placeholder="홍길동"
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
            </div>

            <div className="pm-actionblock">
              <Button variant="danger" size="sm" block onClick={onDelete}>
                사진 삭제
              </Button>
            </div>
          </div>
        </DetailsPanel>
      </div>
    </li>
  );
}

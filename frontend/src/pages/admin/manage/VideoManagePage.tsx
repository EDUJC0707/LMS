/**
 * /admin/videos — 복습영상 등록·관리.
 *
 *   GET   /api/admin/videos                영상 목록
 *   POST  /api/admin/videos                등록(항상 `준비중` 으로 생긴다)
 *   PATCH /api/admin/videos/{id}           메타·자산 수정
 *   POST  /api/admin/videos/{id}/publish   `공개` 전환
 *   POST  /api/admin/videos/{id}/archive   `아카이브` 전환
 *   GET   /api/admin/videos/course-weeks   주차 선택지
 *
 * ## 등록은 한 주차에 여러 번 반복된다
 *
 * 주차마다 2~3강이라 같은 주차·같은 호스팅을 연달아 입력한다. 그래서 저장 후
 * 모달을 닫지 않는 [저장하고 계속] 을 둔다 — 주차·호스팅은 그대로 두고 제목·차시·
 * 재생 ID만 비운다. 차시는 그 주차의 최대 차시 + 1 로 채운다.
 *
 * ## `공개` 는 서버가 조건을 강제한다
 *
 * 주차와 재생 자산이 없으면 400 이다. 화면이 미리 막지 않고 서버 문구를 그대로
 * 보여준다 — 조건을 두 곳에 적으면 한쪽만 바뀐다(판정은 video_admin.publish_blocker).
 */
import { useMemo, useState } from "react";

import { http, useApi, useApiAction } from "../../../api";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  Field,
  Input,
  Loading,
  Modal,
  Select,
  Table,
} from "../../../components";
import "./manage.css";

interface CourseWeekBlock {
  week_id: number;
  week_no: number;
  start_date: string | null;
  course: { course_id: number; name: string };
}

interface VideoRow {
  video_id: number;
  title: string;
  sequence_no: number | null;
  provider: string | null;
  external_ref: string | null;
  duration_seconds: number | null;
  status: string;
  created_at: string | null;
  course_week: CourseWeekBlock | null;
}

/** 폼 상태 — 비어 있는 칸은 빈 문자열이고 서버가 NULL 로 접는다. */
interface FormState {
  title: string;
  course_week_id: string;
  sequence_no: string;
  provider: string;
  external_ref: string;
  duration_seconds: string;
}

const EMPTY_FORM: FormState = {
  title: "",
  course_week_id: "",
  sequence_no: "",
  // 업체는 Mux 로 확정됐다(docs/decisions.md §3). 값집합은 모델에 그대로 남아 있고
  // 여기서는 재생기가 실제로 해석할 수 있는 것만 고르게 한다.
  provider: "mux",
  external_ref: "",
  duration_seconds: "",
};

const STATUS_TONE: Record<string, "neutral" | "success" | "warning"> = {
  준비중: "warning",
  공개: "success",
  아카이브: "neutral",
};

function weekLabel(week: CourseWeekBlock | null): string {
  return week ? `${week.course.name} ${week.week_no}주차` : "—";
}

function runtime(seconds: number | null): string {
  return seconds ? `${Math.round(seconds / 60)}분` : "—";
}

/** 폼 → 요청 본문. 빈 칸은 null 로 보내 서버가 지우게 한다. */
function toPayload(form: FormState) {
  const num = (raw: string) => (raw.trim() === "" ? null : Number(raw));
  return {
    title: form.title.trim(),
    course_week_id: num(form.course_week_id),
    sequence_no: num(form.sequence_no),
    provider: form.provider || null,
    external_ref: form.external_ref.trim() || null,
    duration_seconds: num(form.duration_seconds),
  };
}

export default function VideoManagePage() {
  const list = useApi(
    () => http.get<{ videos: VideoRow[] }>("/admin/videos").then((r) => r.data.videos),
    [],
  );
  const weeks = useApi(
    () =>
      http
        .get<{ course_weeks: CourseWeekBlock[] }>("/admin/videos/course-weeks")
        .then((r) => r.data.course_weeks),
    [],
  );

  const [editing, setEditing] = useState<VideoRow | null>(null);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [query, setQuery] = useState("");

  const rows = list.data ?? [];
  const weekRows = weeks.data ?? [];

  const shown = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return rows;
    return rows.filter(
      (row) =>
        row.title.toLowerCase().includes(needle) ||
        (row.external_ref ?? "").toLowerCase().includes(needle),
    );
  }, [rows, query]);

  /** 그 주차의 다음 차시 — 연달아 등록할 때 손으로 세지 않게 한다. */
  const nextSequence = (weekId: string): string => {
    if (!weekId) return "";
    const used = rows
      .filter((row) => String(row.course_week?.week_id ?? "") === weekId)
      .map((row) => row.sequence_no ?? 0);
    return String((used.length ? Math.max(...used) : 0) + 1);
  };

  const save = useApiAction(async (keepOpen: boolean) => {
    const payload = toPayload(form);
    if (editing) {
      await http.patch(`/admin/videos/${editing.video_id}`, payload);
    } else {
      await http.post("/admin/videos", payload);
    }
    await list.reload();
    if (keepOpen) {
      // 주차·호스팅은 남기고 개별 값만 비운다(파일 머리말 참조).
      setForm((prev) => ({
        ...prev,
        title: "",
        external_ref: "",
        duration_seconds: "",
        sequence_no: nextSequence(prev.course_week_id),
      }));
    } else {
      setOpen(false);
    }
    return true;
  });

  const transition = useApiAction(async (video: VideoRow, verb: "publish" | "archive") => {
    await http.post(`/admin/videos/${video.video_id}/${verb}`);
    await list.reload();
    return true;
  });

  const openCreate = () => {
    setEditing(null);
    setForm({ ...EMPTY_FORM });
    save.clearError();
    setOpen(true);
  };

  const openEdit = (video: VideoRow) => {
    setEditing(video);
    setForm({
      title: video.title,
      course_week_id: String(video.course_week?.week_id ?? ""),
      sequence_no: String(video.sequence_no ?? ""),
      provider: video.provider ?? "",
      external_ref: video.external_ref ?? "",
      duration_seconds: String(video.duration_seconds ?? ""),
    });
    save.clearError();
    setOpen(true);
  };

  if (list.initialLoading) return <Loading label="복습영상을 불러오는 중…" />;
  if (list.error) return <ErrorState description={list.error} onRetry={list.reload} />;

  return (
    <div className="ui-stack">
      <Card
        title="복습영상"
        actions={<Button onClick={openCreate}>영상 등록</Button>}
        padding="none"
      >
        {transition.error && (
          <div className="pm-toolbar">
            <ErrorState description={transition.error} onRetry={transition.clearError} />
          </div>
        )}
        <div className="pm-toolbar">
          <Field label="영상 찾기">
            {(props) => (
              <Input
                {...props}
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            )}
          </Field>
        </div>
        <Table<VideoRow>
          rows={shown}
          rowKey={(row) => row.video_id}
          caption="복습영상 목록"
          empty={<EmptyState title="등록된 영상이 없습니다" />}
          columns={[
            {
              key: "week",
              header: "주차",
              width: "11rem",
              sortValue: (row) =>
                `${row.course_week?.course.name ?? ""}${String(
                  row.course_week?.week_no ?? 999,
                ).padStart(3, "0")}`,
              cell: (row) => weekLabel(row.course_week),
            },
            {
              key: "seq",
              header: "차시",
              numeric: true,
              width: "4rem",
              sortValue: (row) => row.sequence_no ?? 999,
              cell: (row) => (row.sequence_no === null ? "—" : `${row.sequence_no}강`),
            },
            {
              key: "title",
              header: "제목",
              sortValue: (row) => row.title,
              cell: (row) => row.title,
            },
            {
              key: "ref",
              header: "재생 ID",
              width: "12rem",
              sortValue: (row) => row.external_ref ?? "",
              cell: (row) => row.external_ref ?? "—",
            },
            {
              key: "runtime",
              header: "길이",
              numeric: true,
              width: "5rem",
              sortValue: (row) => row.duration_seconds ?? 0,
              cell: (row) => runtime(row.duration_seconds),
            },
            {
              key: "status",
              header: "상태",
              width: "6rem",
              sortValue: (row) => row.status,
              cell: (row) => (
                <Badge tone={STATUS_TONE[row.status] ?? "neutral"}>{row.status}</Badge>
              ),
            },
            {
              key: "actions",
              header: "",
              width: "13rem",
              cell: (row) => (
                <div className="pm-rowactions">
                  <Button size="sm" variant="ghost" onClick={() => openEdit(row)}>
                    수정
                  </Button>
                  {row.status !== "공개" && (
                    <Button
                      size="sm"
                      variant="primary"
                      loading={transition.pending}
                      onClick={() => void transition.run(row, "publish")}
                    >
                      공개
                    </Button>
                  )}
                  {row.status !== "아카이브" && (
                    <Button
                      size="sm"
                      variant="ghost"
                      loading={transition.pending}
                      onClick={() => void transition.run(row, "archive")}
                    >
                      보관
                    </Button>
                  )}
                </div>
              ),
            },
          ]}
        />
      </Card>

      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title={editing ? "영상 수정" : "영상 등록"}
        footer={
          <>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              닫기
            </Button>
            {!editing && (
              <Button
                variant="secondary"
                loading={save.pending}
                onClick={() => void save.run(true)}
              >
                저장하고 계속
              </Button>
            )}
            <Button loading={save.pending} onClick={() => void save.run(false)}>
              저장
            </Button>
          </>
        }
      >
        <div className="ui-stack ui-stack--md">
          {save.error && <ErrorState description={save.error} onRetry={save.clearError} />}

          <Field label="주차">
            {(props) => (
              <Select
                {...props}
                value={form.course_week_id}
                onChange={(e) => {
                  const week_id = e.target.value;
                  setForm((prev) => ({
                    ...prev,
                    course_week_id: week_id,
                    sequence_no: prev.sequence_no || nextSequence(week_id),
                  }));
                }}
              >
                <option value="">선택 안 함</option>
                {weekRows.map((week) => (
                  <option key={week.week_id} value={week.week_id}>
                    {weekLabel(week)}
                  </option>
                ))}
              </Select>
            )}
          </Field>

          <Field label="제목" required>
            {(props) => (
              <Input
                {...props}
                value={form.title}
                onChange={(e) => setForm((prev) => ({ ...prev, title: e.target.value }))}
              />
            )}
          </Field>

          <Field label="차시">
            {(props) => (
              <Input
                {...props}
                type="number"
                min={1}
                value={form.sequence_no}
                onChange={(e) =>
                  setForm((prev) => ({ ...prev, sequence_no: e.target.value }))
                }
              />
            )}
          </Field>

          <Field label="Mux 재생 ID">
            {(props) => (
              <Input
                {...props}
                value={form.external_ref}
                onChange={(e) =>
                  setForm((prev) => ({ ...prev, external_ref: e.target.value }))
                }
              />
            )}
          </Field>

          <Field label="재생 길이(초)">
            {(props) => (
              <Input
                {...props}
                type="number"
                min={0}
                value={form.duration_seconds}
                onChange={(e) =>
                  setForm((prev) => ({ ...prev, duration_seconds: e.target.value }))
                }
              />
            )}
          </Field>
        </div>
      </Modal>
    </div>
  );
}

/**
 * /admin/exams — 시험 회차 목록.
 *
 * API  GET /api/admin/exams  → {exams: [...]}
 *
 * 화면 설계
 * - 회차·응시자·평균·처리 상태를 한 표에서 비교하는 게 이 화면의 전부다.
 *   정렬은 표 헤더로, 좁히기는 이름 검색으로 한다(서버에 검색 파라미터가 없어
 *   불러온 목록 안에서 찾는다 — 회차 수가 적어 문제가 되지 않는다).
 * - 아직 대조하지 못한 답안지가 남은 회차는 그 자체가 할 일이라 눈에 띄게 둔다.
 */
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { http, useApi, useApiAction } from "../../../api";
import {
  Alert,
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
  StatusBadge,
  Table,
} from "../../../components";
import "./manage.css";
import type { ExamKind, ExamListRow } from "./types";

const EXAM_KINDS: ExamKind[] = ["미니테스트", "모의고사"];

/** 평균은 소수가 길게 내려오므로 한 자리로 줄여 읽는다. */
export function score(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

export default function ExamsPage() {
  const navigate = useNavigate();
  const exams = useApi(
    () => http.get<{ exams: ExamListRow[] }>("/admin/exams").then((r) => r.data.exams),
    [],
  );
  const [query, setQuery] = useState("");
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [examDate, setExamDate] = useState("");
  const [kind, setKind] = useState<ExamKind>("미니테스트");

  const create = useApiAction(async () => {
    const { data } = await http.post<{ exam_id: number }>("/admin/exams", {
      name: name.trim(),
      exam_date: examDate,
      kind,
    });
    return data.exam_id;
  });

  const rows = useMemo(() => {
    const list = exams.data ?? [];
    const needle = query.trim();
    if (!needle) return list;
    return list.filter(
      (exam) => exam.name.includes(needle) || String(exam.round_no ?? "").includes(needle),
    );
  }, [exams.data, query]);

  if (exams.loading) return <Loading label="시험 목록을 불러오는 중…" />;
  if (exams.error) return <ErrorState description={exams.error} onRetry={exams.reload} />;

  return (
    <>
    <Card
      title="시험 회차"
      aside={<Button onClick={() => setCreating(true)}>새 회차</Button>}
      padding="none"
    >
      <div className="pm-toolbar pm-cardpad">
        <Field label="회차 찾기">
          {(props) => (
            <Input
              {...props}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="주간모의고사"
              type="search"
            />
          )}
        </Field>
      </div>

      <Table<ExamListRow>
        rows={rows}
        rowKey={(row) => row.exam_id}
        dense
        caption="시험 회차 목록"
        onRowClick={(row) => navigate(`/admin/exams/${row.exam_id}`)}
        empty={
          query.trim() ? (
            <EmptyState title={`“${query.trim()}”과 맞는 회차가 없습니다`} />
          ) : (
            <EmptyState title="아직 등록된 시험이 없습니다" />
          )
        }
        columns={[
          {
            key: "round",
            header: "회차",
            numeric: true,
            width: "4.5rem",
            sortValue: (row) => row.round_no ?? 0,
            cell: (row) => row.round_no ?? "—",
          },
          {
            key: "name",
            header: "시험명",
            sortValue: (row) => row.name,
            cell: (row) => row.name,
          },
          {
            key: "date",
            header: "시험일",
            numeric: true,
            sortValue: (row) => row.exam_date,
            cell: (row) => row.exam_date,
          },
          {
            key: "taker",
            header: "응시",
            numeric: true,
            sortValue: (row) => row.taker_count,
            cell: (row) => `${row.taker_count}명`,
          },
          {
            key: "scored",
            header: "성적 행",
            numeric: true,
            sortValue: (row) => row.score_count,
            cell: (row) => row.score_count,
          },
          {
            key: "average",
            header: "평균",
            numeric: true,
            sortValue: (row) => row.average ?? -1,
            cell: (row) => score(row.average),
          },
          {
            key: "status",
            header: "처리 상태",
            width: "6rem",
            cell: (row) => <StatusBadge status={row.processing_status} />,
          },
          {
            key: "pending",
            header: "미대조 답안지",
            numeric: true,
            sortValue: (row) => row.pending_sheet_count,
            cell: (row) =>
              row.pending_sheet_count > 0 ? (
                <Badge tone="warning">{row.pending_sheet_count}장</Badge>
              ) : (
                <span className="pm-none">없음</span>
              ),
          },
        ]}
      />
    </Card>

    <Modal
      open={creating}
      onClose={() => setCreating(false)}
      title="새 회차"
      footer={
        <>
          <Button onClick={() => setCreating(false)}>취소</Button>
          <Button
            variant="primary"
            loading={create.pending}
            disabled={!name.trim() || !examDate}
            onClick={async () => {
              const id = await create.run();
              if (id === undefined) return;
              setCreating(false);
              setName("");
              setExamDate("");
              setKind("미니테스트");
              navigate(String(id));
            }}
          >
            만들기
          </Button>
        </>
      }
    >
      <div className="ui-stack ui-stack--sm">
        {create.error && <Alert tone="danger">{create.error}</Alert>}
        <Field label="시험명">
          {(props) => (
            <Input {...props} value={name} onChange={(e) => setName(e.target.value)} />
          )}
        </Field>
        <Field label="시험일">
          {(props) => (
            <Input
              {...props}
              type="date"
              value={examDate}
              onChange={(e) => setExamDate(e.target.value)}
            />
          )}
        </Field>
        {/* 지면이 갈린다 — 미니테스트는 답안 카드, 모의고사는 성적 조사 카드다. */}
        <Field label="종류">
          {(props) => (
            <Select
              {...props}
              value={kind}
              onChange={(e) => setKind(e.target.value as ExamKind)}
            >
              {EXAM_KINDS.map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </Select>
          )}
        </Field>
      </div>
    </Modal>
    </>
  );
}

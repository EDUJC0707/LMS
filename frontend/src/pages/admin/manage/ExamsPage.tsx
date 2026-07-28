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

import { http, useApi } from "../../../api";
import {
  Badge,
  Card,
  EmptyState,
  ErrorState,
  Field,
  Input,
  Loading,
  PageHeader,
  StatusBadge,
  Table,
} from "../../../components";
import "./manage.css";
import type { ExamListRow } from "./types";

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

  const rows = useMemo(() => {
    const list = exams.data ?? [];
    const needle = query.trim();
    if (!needle) return list;
    return list.filter(
      (exam) => exam.name.includes(needle) || String(exam.round_no ?? "").includes(needle),
    );
  }, [exams.data, query]);

  const pending = (exams.data ?? []).filter((exam) => exam.pending_sheet_count > 0);

  return (
    <>
      <PageHeader
        title="시험·성적"
        description="회차별 응시 인원과 평균, 채점 진행 상황을 봅니다. 회차를 누르면 학생별 점수와 문항 분석이 열립니다."
      />

      {exams.loading ? (
        <Loading label="시험 목록을 불러오는 중…" />
      ) : exams.error ? (
        <ErrorState description={exams.error} onRetry={exams.reload} />
      ) : (
        <Card
          title="시험 회차"
          aside={
            pending.length > 0
              ? `${pending.length}개 회차에 미대조 답안지가 남아 있습니다`
              : `${(exams.data ?? []).length}개 회차`
          }
          padding="none"
        >
          <div style={{ padding: "var(--space-lg) var(--space-lg) 0" }}>
            <div className="pm-toolbar">
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
          </div>

          <Table<ExamListRow>
            rows={rows}
            rowKey={(row) => row.exam_id}
            dense
            caption="시험 회차 목록. 행을 누르면 상세로 이동합니다."
            onRowClick={(row) => navigate(`/admin/exams/${row.exam_id}`)}
            empty={
              query.trim() ? (
                <EmptyState
                  title={`“${query.trim()}”과 맞는 회차가 없습니다`}
                  description="검색어를 지우면 전체 회차가 다시 보입니다."
                />
              ) : (
                <EmptyState
                  title="아직 등록된 시험이 없습니다"
                  description="시험을 만들고 답안지를 올리면 여기에 회차가 쌓입니다."
                />
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
                    <span style={{ color: "var(--color-muted)" }}>없음</span>
                  ),
              },
            ]}
          />
        </Card>
      )}
    </>
  );
}

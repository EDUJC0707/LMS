/**
 * /admin/aliases — 컬럼 별칭 · 학교 별칭 (FLOW 2-2 · 5-1).
 *
 * API
 *   GET    /api/admin/aliases                  두 표
 *   POST   /api/admin/aliases                  {table, alias, target}
 *   PATCH  /api/admin/aliases/{table}/{id}     {target}
 *   DELETE /api/admin/aliases/{table}/{id}
 *
 * 화면 설계
 * - **표가 둘이라 카드도 둘이다**(FLOW 2-2). 붙는 값이 컬럼 별칭은 닫힌
 *   목록(열)이고 학교 별칭은 자유 입력(정식 이름)이라 그 칸만 다르다 —
 *   나머지가 같아서 카드 하나를 두 번 쓴다.
 * - **전체 레벨에 둔다**(FLOW 5-1). 표가 학원 구분 없이 전역이라 어느 반을
 *   열어도 같은 표고, 한 번 잘못 붙이면 이후 모든 명단이 조용히 오염된다.
 * - **별칭 칸은 고칠 수 없다.** 다른 머리줄을 붙이는 것은 새 줄이고, 이 줄에서
 *   고칠 것은 어디에 붙느냐뿐이다(백엔드 AliasDetailView 와 같은 계약).
 * - 학교 별칭에서 **정식 이름을 자기 자신으로 적은 줄이 곧 새 학교 등록**이다
 *   (FLOW 2-2 의 두 가지 일 — 새 학교 등록·다른 이름 붙이기 — 이 한 표에서
 *   끝난다). 그래서 "학교 만들기" 버튼이 따로 없다.
 * - 적어 넣은 별칭은 공백·구두점을 뗀 형태로 저장돼 돌아온다(서버 alias_key).
 *   화면이 보여 주는 값과 실제로 대조되는 값이 갈리지 않게.
 */
import { FormEvent, useEffect, useState } from "react";

import { http, useApi, useApiAction } from "../../../api";
import {
  Alert,
  Button,
  Card,
  ErrorState,
  Field,
  Input,
  Loading,
  Select,
  Table,
} from "../../../components";
import "./manage.css";
import { EntryField, FIELD_LABELS } from "./paste";
import type { AliasRow, AliasTables } from "./types";

/** 컬럼 별칭이 붙을 수 있는 열 — 값집합은 서버(aliases.COLUMN_FIELDS)가 정한다. */
const FIELD_OPTIONS = (Object.keys(FIELD_LABELS) as EntryField[]).map((field) => ({
  value: field,
  label: FIELD_LABELS[field],
}));

const detailUrl = (table: string, id: number) =>
  `/admin/aliases/${encodeURIComponent(table)}/${id}`;

export default function AliasesPage() {
  const list = useApi(async () => {
    const { data } = await http.get<AliasTables>("/admin/aliases");
    return data;
  }, []);

  return (
    <>
      <AliasCard
        title="컬럼 별칭"
        table="컬럼"
        targetLabel="열"
        rows={list.data?.columns ?? []}
        options={FIELD_OPTIONS}
        loading={list.initialLoading}
        error={list.error}
        onReload={list.reload}
      />
      <AliasCard
        title="학교 별칭"
        table="학교"
        targetLabel="정식 이름"
        rows={list.data?.schools ?? []}
        loading={list.initialLoading}
        error={list.error}
        onReload={list.reload}
      />
    </>
  );
}

function AliasCard({
  title,
  table,
  targetLabel,
  rows,
  options,
  loading,
  error,
  onReload,
}: {
  title: string;
  /** 서버가 아는 표 이름 — 경로와 본문에 그대로 실린다. */
  table: string;
  /** 붙는 값 칸의 이름. 표 머리와 입력 라벨이 같은 문자열을 쓴다. */
  targetLabel: string;
  rows: AliasRow[];
  /** 주면 붙는 값이 닫힌 목록(컬럼 별칭), 안 주면 자유 입력(학교 별칭). */
  options?: { value: string; label: string }[];
  loading: boolean;
  error: string | null;
  onReload: () => Promise<void>;
}) {
  const [alias, setAlias] = useState("");
  const [target, setTarget] = useState(options ? options[0].value : "");

  const add = useApiAction(async () => {
    await http.post("/admin/aliases", { table, alias, target });
    return true;
  });
  const retarget = useApiAction(async (id: number, next: string) => {
    await http.patch(detailUrl(table, id), { target: next });
    return true;
  });
  const remove = useApiAction(async (id: number) => {
    await http.delete(detailUrl(table, id));
    return true;
  });
  const failure = add.error ?? retarget.error ?? remove.error;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!(await add.run())) return;
    setAlias("");
    await onReload();
  };

  const commit = async (id: number, next: string) => {
    if (await retarget.run(id, next)) await onReload();
  };

  const drop = async (id: number) => {
    if (await remove.run(id)) await onReload();
  };

  return (
    <Card title={title} padding="none">
      <form className="pm-cardpad pm-toolbar" onSubmit={submit}>
        <Field label="별칭">
          {(props) => (
            <Input {...props} value={alias} onChange={(e) => setAlias(e.target.value)} />
          )}
        </Field>
        <Field label={targetLabel}>
          {(props) =>
            options ? (
              <Select {...props} value={target} onChange={(e) => setTarget(e.target.value)}>
                {options.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </Select>
            ) : (
              <Input {...props} value={target} onChange={(e) => setTarget(e.target.value)} />
            )
          }
        </Field>
        <Button type="submit" variant="primary" loading={add.pending}>
          추가
        </Button>
      </form>

      {failure && (
        <div className="pm-cardpad">
          <Alert tone="danger">{failure}</Alert>
        </div>
      )}

      {loading ? (
        <Loading label="별칭표를 불러오는 중…" />
      ) : error ? (
        <ErrorState description={error} onRetry={onReload} />
      ) : (
        <Table<AliasRow>
          rows={rows}
          rowKey={(row) => row.id}
          dense
          caption={title}
          columns={[
            {
              key: "alias",
              header: "별칭",
              cell: (row) => row.alias,
              sortValue: (row) => row.alias,
            },
            {
              key: "target",
              header: targetLabel,
              sortValue: (row) => row.target,
              cell: (row) =>
                options ? (
                  <Select
                    value={row.target}
                    aria-label={`${row.alias} ${targetLabel}`}
                    onChange={(e) => void commit(row.id, e.target.value)}
                  >
                    {options.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </Select>
                ) : (
                  <TargetInput
                    value={row.target}
                    label={`${row.alias} ${targetLabel}`}
                    onCommit={(next) => void commit(row.id, next)}
                  />
                ),
            },
            {
              key: "remove",
              header: "",
              width: "6rem",
              cell: (row) => (
                <Button size="sm" variant="ghost" onClick={() => void drop(row.id)}>
                  삭제
                </Button>
              ),
            },
          ]}
        />
      )}
    </Card>
  );
}

/**
 * 자유 입력 칸 — 칸을 떠날 때만 저장한다.
 *
 * 글자마다 보내면 `숙명여자고등학교` 를 적는 동안 `숙`·`숙명`… 이 차례로
 * 저장된다. 저장 버튼을 따로 두지 않는 이유는 줄마다 하나씩 생기기 때문이다.
 */
function TargetInput({
  value,
  label,
  onCommit,
}: {
  value: string;
  label: string;
  onCommit: (next: string) => void;
}) {
  const [text, setText] = useState(value);
  useEffect(() => setText(value), [value]);
  return (
    <Input
      value={text}
      aria-label={label}
      onChange={(e) => setText(e.target.value)}
      onBlur={() => {
        const next = text.trim();
        if (next && next !== value) onCommit(next);
        else setText(value);
      }}
    />
  );
}

/**
 * 학생 검색·선택기 — GET /api/admin/students (직원 공통 권한).
 *
 * 워크북 업로드·매칭처럼 "누구 것인지" 고르는 자리에 쓴다. 예전에는 출결 회차
 * 출석부에서 명단을 빌려 와야 했고(출결입력 권한이 없으면 후보가 0명), 그래서
 * 조교는 사진을 올릴 수 없었다. 이제 명부 API 가 직원 공통이라 그 우회가 사라졌다.
 *
 * 설계
 * - 이름·원번을 입력하면 서버가 부분일치로 찾아 준다(전화도 검색되지만 응답에는
 *   전화가 없다 — 역방향 조회 방지. 화면도 서버가 준 것만 그린다).
 * - 후보는 한 페이지(20명)만 그린다. 더 있으면 "더 좁혀 주세요"라고 말한다.
 * - 고르고 나면 목록을 접고 고른 학생만 남긴다 — 잘못 고른 것을 눈으로 확인할 수 있게.
 */
import { useEffect, useState } from "react";

import { http, useApi } from "../../../api";
import { Badge, Button, Field, Input, Spinner } from "../../../components";
import { DirectoryPage, DirectoryStudent, directoryParams } from "./directory";
import "./manage.css";

export interface StudentPickerProps {
  /** 지금 고른 학생. 없으면 null. */
  value: DirectoryStudent | null;
  onChange: (student: DirectoryStudent | null) => void;
  label?: string;
  hint?: string;
  required?: boolean;
}

export function StudentPicker({
  value,
  onChange,
  label = "학생",
  hint,
  required,
}: StudentPickerProps) {
  const [term, setTerm] = useState("");
  const [query, setQuery] = useState("");

  // 글자를 칠 때마다 부르지 않는다 — 멈춘 뒤에만 한 번.
  useEffect(() => {
    const timer = setTimeout(() => setQuery(term.trim()), 250);
    return () => clearTimeout(timer);
  }, [term]);

  const found = useApi<DirectoryPage | null>(async () => {
    if (query.length === 0) return null;
    const { data } = await http.get<DirectoryPage>("/admin/students", {
      params: directoryParams({ q: query }),
    });
    return data;
  }, [query]);

  const results = found.data?.results ?? [];
  const total = found.data?.count ?? 0;

  if (value) {
    return (
      <div className="pm-picker">
        <p className="pm-picker__label">{label}</p>
        <div className="pm-picker__chosen">
          <span className="pm-picker__name">
            <span className="num">{value.unique_id || "원번 없음"}</span>{" "}
            {value.name ?? "이름 미등록"}
          </span>
          {value.current_class && <Badge tone="outline">{value.current_class}</Badge>}
          {value.enrollment_status !== "등록" && (
            <Badge tone="warning">{value.enrollment_status}</Badge>
          )}
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              onChange(null);
              setTerm("");
            }}
          >
            바꾸기
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="pm-picker">
      <Field
        label={label}
        required={required}
        hint={hint ?? "이름이나 원번을 입력하면 후보가 나타납니다."}
        error={found.error}
      >
        {(props) => (
          <Input
            {...props}
            type="search"
            value={term}
            onChange={(event) => setTerm(event.target.value)}
            placeholder="김하늘 · 26001"
            autoComplete="off"
          />
        )}
      </Field>

      {query.length > 0 && (
        <div className="pm-picker__panel">
          {found.loading ? (
            <p className="pm-picker__msg">
              <Spinner /> 찾는 중…
            </p>
          ) : results.length === 0 ? (
            <p className="pm-picker__msg">
              &lsquo;{query}&rsquo; 에 해당하는 학생이 없습니다. 이름이나 원번을 다시 확인해
              주세요.
            </p>
          ) : (
            <>
              <p className="pm-picker__msg" role="status">
                {total}명 중 {results.length}명
                {total > results.length ? " — 더 좁혀 주세요" : ""}
              </p>
              <ul className="pm-picker__list">
                {results.map((student) => (
                  <li key={student.student_id}>
                    <button
                      type="button"
                      className="pm-picker__option"
                      onClick={() => {
                        onChange(student);
                        setTerm("");
                      }}
                    >
                      <span className="pm-picker__name">
                        <span className="num">{student.unique_id || "원번 없음"}</span>{" "}
                        {student.name ?? "이름 미등록"}
                      </span>
                      <span className="pm-picker__meta">
                        {student.grade || "학년 미입력"}
                        {student.current_class ? ` · ${student.current_class}` : ""}
                        {student.enrollment_status !== "등록"
                          ? ` · ${student.enrollment_status}`
                          : ""}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}
    </div>
  );
}

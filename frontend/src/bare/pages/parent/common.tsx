/** 학부모 공용 — 자녀 선택 드롭다운(1명이면 숨김, PRD 3.4). URL 쿼리로 유지. */
import { useSearchParams } from "react-router-dom";

import { useMe } from "../../MeContext";

export function useChild(): {
  studentId: number | null;
  picker: JSX.Element | null;
} {
  const { me } = useMe();
  const [params, setParams] = useSearchParams();
  const children = me?.children ?? [];
  const raw = params.get("student_id");
  const studentId =
    raw !== null ? Number(raw) : children.length > 0 ? children[0].student_id : null;

  const picker =
    children.length <= 1 ? null : (
      <p className="inline">
        자녀 선택:{" "}
        <select
          value={studentId ?? ""}
          onChange={(e) => {
            const next = new URLSearchParams(params);
            next.set("student_id", e.target.value);
            setParams(next);
          }}
        >
          {children.map((child) => (
            <option key={child.student_id} value={child.student_id}>
              {child.name ?? `학생 ${child.student_id}`} ({child.grade})
            </option>
          ))}
        </select>
      </p>
    );

  return { studentId, picker };
}

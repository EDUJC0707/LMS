/**
 * 자녀 선택 — 학부모 화면 전체가 공유하는 단 하나의 컨텍스트.
 *
 * - 자녀가 1명이면 드롭다운을 아예 그리지 않는다(PRD 3.4).
 * - 고른 자녀는 localStorage 에 남아 페이지를 옮겨도 유지된다.
 * - 모든 학부모 API 에 ?student_id= 로 실어 보낸다.
 *
 * 라우터·프로바이더를 건드릴 수 없으므로 React Context 대신 모듈 스토어를 쓴다
 * (useSyncExternalStore — 같은 화면의 여러 컴포넌트가 항상 같은 값을 본다).
 */
import { ReactNode, useSyncExternalStore } from "react";

import { MeChild } from "../../api";
import { useMe } from "../../auth";
import { Select } from "../../components";
import "./parent.css";

const STORAGE_KEY = "hjc.parent.child";

const listeners = new Set<() => void>();

function readStored(): number | null {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw === null) return null;
    const parsed = Number(raw);
    return Number.isFinite(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

let selected: number | null = readStored();

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function snapshot(): number | null {
  return selected;
}

function selectChild(studentId: number): void {
  selected = studentId;
  try {
    window.localStorage.setItem(STORAGE_KEY, String(studentId));
  } catch {
    // 프라이빗 모드 등 저장 실패 — 이번 세션 동안만 유지된다.
  }
  listeners.forEach((listener) => listener());
}

export interface ChildContext {
  /** 자녀가 없으면 null — 이때는 API 를 부르지 않는다. */
  studentId: number | null;
  child: MeChild | null;
  children: MeChild[];
  /** 자녀 2명 이상일 때만 요소가 있다. PageHeader actions 에 넣는다. */
  picker: ReactNode;
}

export function useChild(): ChildContext {
  const { me } = useMe();
  const children = me?.children ?? [];
  const stored = useSyncExternalStore(subscribe, snapshot, snapshot);

  // 저장된 값이 이 학부모의 자녀가 아니면(계정 전환 등) 첫째로 되돌린다.
  const known = children.some((entry) => entry.student_id === stored);
  const studentId = known ? stored : (children[0]?.student_id ?? null);
  const child = children.find((entry) => entry.student_id === studentId) ?? null;

  const picker =
    children.length <= 1 ? null : (
      <div className="parent-childpick">
        <label className="parent-childpick__label" htmlFor="parent-child">
          자녀
        </label>
        <Select
          id="parent-child"
          className="parent-childpick__select"
          value={studentId === null ? "" : String(studentId)}
          onChange={(event) => selectChild(Number(event.target.value))}
        >
          {children.map((entry) => (
            <option key={entry.student_id} value={entry.student_id}>
              {entry.name ?? `학생 ${entry.student_id}`} · {entry.grade}
            </option>
          ))}
        </Select>
      </div>
    );

  return { studentId, child, children, picker };
}

/** 자녀가 한 명도 연결돼 있지 않을 때 화면에 띄우는 문구. */
export const NO_CHILD_TITLE = "연결된 자녀가 없습니다";
export const NO_CHILD_DESC =
  "학원에서 자녀 계정을 연결하면 이 화면에 출결·성적이 나타납니다. 연결이 안 돼 있다면 학원으로 문의해 주세요.";

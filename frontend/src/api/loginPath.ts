/**
 * 로그인 경로 표 — 백엔드 2026-07-28 개편(단일 준거).
 *
 * 소비자(학생·학부모)는 `/api/auth/login` 하나를 공유한다. 역할 판정은
 * 서버가 `users.role` 컬럼으로 하고, 아이디의 `p` 접미사는 쓰지 않는다.
 * 구 경로 `/auth/login/student` · `/auth/login/parent` 는 서버에서 삭제됐다(404).
 *
 * 의존성 없는 순수 모듈이라 node:test 로 그대로 검증된다.
 */

export type LoginKind = "consumer" | "admin";

export const LOGIN_PATH: Record<LoginKind, string> = {
  consumer: "/auth/login",
  admin: "/auth/login/admin",
};

export function loginPathFor(kind: LoginKind): string {
  return LOGIN_PATH[kind];
}

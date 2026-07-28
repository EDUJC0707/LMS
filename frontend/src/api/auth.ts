/**
 * 인증 엔드포인트 래퍼.
 *
 * 로그인은 두 갈래다(2026-07-28 백엔드 개편):
 *   consumer → POST /api/auth/login        학생·학부모 공용
 *   admin    → POST /api/auth/login/admin  직원 전용(화면에서 링크하지 않는다)
 *
 * 어느 쪽이든 성공 응답의 `role` 로 홈을 정한다(homePathFor). 아이디의 `p`
 * 접미사는 역할 판정에 쓰지 않는다 — 서버가 users.role 컬럼으로 판정한다.
 */
import { ensureCsrf, http } from "./http";
import { LOGIN_PATH, LoginKind, loginPathFor } from "./loginPath";
import { Me } from "./types";

export { LOGIN_PATH, loginPathFor };
export type { LoginKind };

export async function login(kind: LoginKind, loginId: string, password: string): Promise<Me> {
  await ensureCsrf();
  const { data } = await http.post<Me>(loginPathFor(kind), {
    login_id: loginId,
    password,
  });
  return data;
}

export async function logout(): Promise<void> {
  await ensureCsrf();
  await http.post("/auth/logout");
}

export async function changePassword(
  currentPassword: string,
  newPassword: string,
): Promise<void> {
  await ensureCsrf();
  await http.post("/auth/password", {
    current_password: currentPassword,
    new_password: newPassword,
  });
}

export async function fetchMe(): Promise<Me> {
  const { data } = await http.get<Me>("/me");
  return data;
}

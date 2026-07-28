/** 인증 엔드포인트 래퍼 — PRD §4 로그인 3종 분리. */
import { ensureCsrf, http } from "./http";
import { Me } from "./types";

export type LoginKind = "student" | "parent" | "admin";

export const LOGIN_PATH: Record<LoginKind, string> = {
  student: "/auth/login/student",
  parent: "/auth/login/parent",
  admin: "/auth/login/admin",
};

export async function login(kind: LoginKind, loginId: string, password: string): Promise<Me> {
  await ensureCsrf();
  const { data } = await http.post<Me>(LOGIN_PATH[kind], {
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

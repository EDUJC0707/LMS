/** API 계층 단일 진입점. 화면에서는 여기서만 import 한다. */
export { http, ensureCsrf, mediaUrl } from "./http";
export { toMessage, statusOf, isForbidden } from "./errors";
export { login, logout, changePassword, fetchMe, LOGIN_PATH } from "./auth";
export type { LoginKind } from "./auth";
export { STAFF_ROLES, isStaff, homePathFor } from "./types";
export type { Me, MeChild, MeStudent, Role, Feature } from "./types";
export { useApi, useApiAction } from "./useApi";
export type { ApiState } from "./useApi";

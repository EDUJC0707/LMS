/**
 * bare 프런트 API 계층 — 기존 axios 클라이언트(src/api/client) 재사용.
 *
 * - CSRF: Django 기본 계약(쿠키 csrftoken → 헤더 X-CSRFToken). axios 는
 *   cross-origin(5173→8000)에서는 withXSRFToken 을 켜야 헤더를 실어준다.
 * - 모든 요청/응답을 로그에 남겨 각 페이지 하단 디버그 패널(<details>)에서
 *   원문 JSON 을 볼 수 있게 한다(공부 목적).
 */
import { AxiosError } from "axios";

import { apiClient } from "../api/client";

apiClient.defaults.xsrfCookieName = "csrftoken";
apiClient.defaults.xsrfHeaderName = "X-CSRFToken";
apiClient.defaults.withCredentials = true;
apiClient.defaults.withXSRFToken = true;

export const api = apiClient;

const apiBase: string =
  (import.meta.env.VITE_API_URL as string | undefined) ?? "http://localhost:8000/api";
export const backendOrigin = apiBase.replace(/\/api\/?$/, "");

/** 백엔드가 내리는 상대 미디어 경로(media/...)를 절대 URL 로 보정. */
export function mediaUrl(url: string): string {
  if (/^https?:\/\//.test(url)) return url;
  return `${backendOrigin}/${url.replace(/^\//, "")}`;
}

export interface ApiLogEntry {
  at: string;
  method: string;
  url: string;
  status: number | string;
  data: unknown;
}

const entries: ApiLogEntry[] = [];
let version = 0;
const listeners = new Set<() => void>();

export function subscribeApiLog(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
export function apiLogVersion(): number {
  return version;
}
export function apiLogEntries(): ApiLogEntry[] {
  return entries;
}

function record(
  method: string | undefined,
  url: string | undefined,
  status: number | string,
  data: unknown,
) {
  entries.unshift({
    at: new Date().toLocaleTimeString(),
    method: (method ?? "?").toUpperCase(),
    url: url ?? "?",
    status,
    data,
  });
  if (entries.length > 30) entries.pop();
  version += 1;
  listeners.forEach((listener) => listener());
}

apiClient.interceptors.response.use(
  (response) => {
    record(response.config.method, response.config.url, response.status, response.data);
    return response;
  },
  (error: AxiosError) => {
    record(
      error.config?.method,
      error.config?.url,
      error.response?.status ?? "network",
      error.response?.data ?? error.message,
    );
    return Promise.reject(error);
  },
);

/** 에러를 사람이 읽는 한 줄로 — 400/403 의 detail 메시지를 그대로 보여준다. */
export function errMsg(error: unknown): string {
  const axiosError = error as AxiosError<unknown>;
  if (axiosError && axiosError.isAxiosError) {
    const status = axiosError.response?.status;
    const data = axiosError.response?.data;
    let body: string;
    if (data && typeof data === "object" && "detail" in (data as Record<string, unknown>)) {
      body = String((data as Record<string, unknown>).detail);
    } else if (data !== undefined) {
      body = JSON.stringify(data);
    } else {
      body = axiosError.message;
    }
    return status ? `${status} — ${body}` : body;
  }
  return error instanceof Error ? error.message : String(error);
}

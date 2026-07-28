/**
 * 에러 규약 — 서버가 내려준 메시지를 "사람이 읽는 한 문장"으로 바꾼다.
 *
 * 백엔드 계약(DRF):
 *   400 { "detail": "..." }  또는 { "필드명": ["..."] }
 *   403 { "detail": "..." }  권한 없음 / 비로그인
 *   404 { "detail": "..." }  없는 리소스
 *
 * 화면 규약: 상태코드 숫자를 사용자에게 보여주지 않는다. detail 이 있으면
 * 그대로 쓰고, 없을 때만 상태코드별 기본 문구로 대체한다.
 */
import { AxiosError } from "axios";

const FALLBACK: Record<number, string> = {
  400: "입력한 내용을 다시 확인해 주세요.",
  401: "로그인이 필요합니다.",
  403: "이 기능을 사용할 권한이 없습니다.",
  404: "요청한 정보를 찾을 수 없습니다.",
  409: "이미 처리된 요청입니다.",
  413: "파일 용량이 너무 큽니다.",
  429: "요청이 너무 잦습니다. 잠시 후 다시 시도해 주세요.",
  500: "서버에 문제가 생겼습니다. 잠시 후 다시 시도해 주세요.",
  502: "서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.",
  503: "서버 점검 중입니다. 잠시 후 다시 시도해 주세요.",
};

function fromBody(data: unknown): string | null {
  if (typeof data === "string" && data.trim() && !data.trim().startsWith("<")) {
    return data.trim();
  }
  if (!data || typeof data !== "object") return null;

  const record = data as Record<string, unknown>;
  if (typeof record.detail === "string") return record.detail;

  // DRF 필드 에러: { "login_id": ["이 필드는 필수입니다."] }
  const messages: string[] = [];
  for (const value of Object.values(record)) {
    if (typeof value === "string") messages.push(value);
    else if (Array.isArray(value)) {
      for (const item of value) if (typeof item === "string") messages.push(item);
    }
  }
  return messages.length > 0 ? messages.join(" ") : null;
}

/** 어떤 예외든 화면에 그대로 띄울 수 있는 한 문장으로 만든다. */
export function toMessage(error: unknown): string {
  const axiosError = error as AxiosError<unknown>;
  if (axiosError?.isAxiosError) {
    if (!axiosError.response) {
      return "서버에 연결하지 못했습니다. 네트워크 상태를 확인해 주세요.";
    }
    const body = fromBody(axiosError.response.data);
    if (body) return body;
    return FALLBACK[axiosError.response.status] ?? "요청을 처리하지 못했습니다.";
  }
  if (error instanceof Error && error.message) return error.message;
  return "요청을 처리하지 못했습니다.";
}

/** 비로그인/권한없음 판별 — 화면 가드에서 쓴다. */
export function statusOf(error: unknown): number | null {
  const axiosError = error as AxiosError;
  return axiosError?.isAxiosError ? (axiosError.response?.status ?? null) : null;
}

export function isForbidden(error: unknown): boolean {
  const status = statusOf(error);
  return status === 401 || status === 403;
}

/**
 * 실제 앱의 axios 인스턴스.
 *
 * - baseURL 은 "/api" 고정. 개발에서는 vite 프록시가 localhost:8000 으로
 *   넘긴다(vite.config.ts). 같은 오리진이므로 세션·CSRF 쿠키가 그대로 붙는다.
 * - Django CSRF 계약: 쿠키 csrftoken → 헤더 X-CSRFToken.
 * - /bare 는 별도 인스턴스(src/api/client.ts)를 쓴다. 이 파일과 분리돼 있으니
 *   여기를 고쳐도 /bare 는 영향받지 않는다.
 */
import axios from "axios";

export const http = axios.create({
  baseURL: "/api",
  withCredentials: true,
  xsrfCookieName: "csrftoken",
  xsrfHeaderName: "X-CSRFToken",
  withXSRFToken: true,
  headers: { "Content-Type": "application/json" },
});

let csrfReady: Promise<void> | null = null;

/** 부팅 시 1회. csrftoken 쿠키를 받아 둔다(POST 전에 반드시 끝나 있어야 한다). */
export function ensureCsrf(): Promise<void> {
  if (!csrfReady) {
    csrfReady = http
      .get("/auth/csrf")
      .then(() => undefined)
      .catch(() => undefined);
  }
  return csrfReady;
}

/**
 * 백엔드가 내려주는 상대 미디어 경로(media/...)를 브라우저가 쓸 수 있는
 * 경로로 보정. 개발에서는 /media 프록시가 받아 준다.
 */
export function mediaUrl(url: string): string {
  if (/^https?:\/\//.test(url)) return url;
  return `/${url.replace(/^\//, "")}`;
}

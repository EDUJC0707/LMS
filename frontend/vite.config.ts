import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// https://vite.dev/config/
// 세션(워크트리)마다 백엔드 포트가 다르다 — 안 나누면 먼저 뜬 세션이 8000 을
// 물고, 다른 세션의 프런트가 **남의 DB 를 보면서 멀쩡히 도는** 일이 생긴다
// (2026-08-11 실제: payment 세션 서버에 meet 세션 화면이 붙어 있었다).
//   VITE_API_TARGET=http://127.0.0.1:8001 npm run dev -- --port 5174
const API_TARGET = process.env.VITE_API_TARGET ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // 프런트는 항상 같은 오리진의 /api 로 호출한다(src/api/http.ts baseURL: "/api").
    // 개발 중에는 이 프록시가 Django로 넘겨준다 — CSRF·세션 쿠키가
    // 같은 오리진 쿠키가 되어 SameSite 문제 없이 동작한다.
    proxy: {
      "/api": { target: API_TARGET, changeOrigin: false },
      // 워크북 사진 등 개발용 로컬 미디어(Django DEBUG 서빙).
      "/media": { target: API_TARGET, changeOrigin: false },
    },
  },
});

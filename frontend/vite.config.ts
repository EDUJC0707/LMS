import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // 프런트는 항상 같은 오리진의 /api 로 호출한다(src/api/http.ts baseURL: "/api").
    // 개발 중에는 이 프록시가 Django(8000)로 넘겨준다 — CSRF·세션 쿠키가
    // 같은 오리진 쿠키가 되어 SameSite 문제 없이 동작한다.
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: false },
      // 워크북 사진 등 개발용 로컬 미디어(Django DEBUG 서빙).
      "/media": { target: "http://localhost:8000", changeOrigin: false },
    },
  },
});

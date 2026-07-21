import axios from "axios";

// 공용 axios 인스턴스. baseURL 은 .env 의 VITE_API_URL 에서 주입.
export const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_URL,
  withCredentials: true, // 세션 인증 쿠키 전송
  headers: {
    "Content-Type": "application/json",
  },
});

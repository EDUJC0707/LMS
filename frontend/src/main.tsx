import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import ReactDOM from "react-dom/client";
import { RouterProvider } from "react-router-dom";

import { MeProvider } from "./auth/MeProvider";
import { ToastProvider } from "./components/Toast";
import { router } from "./routes";
import "./index.css";

const queryClient = new QueryClient();

// 프로바이더 순서 고정: 인증 상태(MeProvider) → 토스트 → 라우터.
// 라우터 안 어디서든 useMe()·useToast() 를 쓸 수 있다.
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <MeProvider>
        <ToastProvider>
          <RouterProvider router={router} />
        </ToastProvider>
      </MeProvider>
    </QueryClientProvider>
  </React.StrictMode>,
);

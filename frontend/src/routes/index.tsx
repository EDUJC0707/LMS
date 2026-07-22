import { createBrowserRouter } from "react-router-dom";

import App from "../App";
import BareApp from "../bare/BareApp";
import AdminHome from "./AdminHome";
import ParentHome from "./ParentHome";
import StudentHome from "./StudentHome";

// 역할별 진입 라우트 placeholder. 인증·가드·중첩 라우트는 이후 추가.
// /bare/* 는 기능 전시용 bare 프런트(디자인 없음) — 기존 화면과 완전 분리.
export const router = createBrowserRouter([
  { path: "/bare/*", element: <BareApp /> },
  {
    path: "/",
    element: <App />,
    children: [
      { index: true, element: <StudentHome /> },
      { path: "student", element: <StudentHome /> },
      { path: "parent", element: <ParentHome /> },
      { path: "admin", element: <AdminHome /> },
    ],
  },
]);

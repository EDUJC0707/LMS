/**
 * 라우터 — 전체 화면이 여기 한 곳에 등록돼 있다.
 *
 * ⚠ 이 파일은 기반 계약이다. 화면을 맡은 에이전트는 **자기 페이지 파일만**
 *   채우고 이 파일은 건드리지 않는다(동시 편집 충돌 방지).
 *
 * 구조:
 *   /login                          학생·학부모 공용(비로그인 전용)
 *   /login/admin                    직원 전용 — 어디서도 링크하지 않는다
 *   /  (RequireAuth)                셸 + 인증 필요. must_change_password 강제 유도
 *     ├ /student/*                  RequireRole 학생
 *     ├ /parent/*                   RequireRole 학부모
 *     ├ /admin/*                    RequireRole 직원 + 화면별 RequireFeature
 *     └ /boards /notifications /password   전 역할 공통
 */
import { Navigate, createBrowserRouter } from "react-router-dom";

import { RedirectIfSignedIn, RequireAuth, RequireFeature, RequireRole } from "../auth/guards";
import { RoleHome } from "./RoleHome";
import { AdminLoginPage, ConsumerLoginPage } from "../pages/auth/LoginPage";

import StudentHomePage from "../pages/student/StudentHomePage";
import StudentGradesPage from "../pages/student/StudentGradesPage";
import StudentGradeDetailPage from "../pages/student/StudentGradeDetailPage";
import StudentClinicPage from "../pages/student/StudentClinicPage";
import StudentMakeupPage from "../pages/student/StudentMakeupPage";
import StudentWorkbookPage from "../pages/student/StudentWorkbookPage";
import StudentVideoPage from "../pages/student/StudentVideoPage";
import StudentPaymentPage from "../pages/student/StudentPaymentPage";

import ParentHomePage from "../pages/parent/ParentHomePage";
import ParentGradesPage from "../pages/parent/ParentGradesPage";
import ParentGradeDetailPage from "../pages/parent/ParentGradeDetailPage";
import ParentWorkbookPage from "../pages/parent/ParentWorkbookPage";
import ParentMakeupPage from "../pages/parent/ParentMakeupPage";
import ParentPaymentPage from "../pages/parent/ParentPaymentPage";

import AdminDashboardPage from "../pages/admin/ops/AdminDashboardPage";
import AttendancePage from "../pages/admin/ops/AttendancePage";
import AttendanceSessionPage from "../pages/admin/ops/AttendanceSessionPage";
import MakeupOpsPage from "../pages/admin/ops/MakeupOpsPage";
import CounselingPage from "../pages/admin/ops/CounselingPage";
import PaymentsPage from "../pages/admin/ops/PaymentsPage";

import StaffPage from "../pages/admin/manage/StaffPage";
import AccountsPage from "../pages/admin/manage/AccountsPage";
import AliasesPage from "../pages/admin/manage/AliasesPage";
import StudentDetailPage from "../pages/admin/manage/StudentDetailPage";
import ClassesPage from "../pages/admin/manage/ClassesPage";
import ClinicManagePage from "../pages/admin/manage/ClinicManagePage";
import ExamsPage from "../pages/admin/manage/ExamsPage";
import ExamDetailPage from "../pages/admin/manage/ExamDetailPage";
import SheetReviewPage from "../pages/admin/manage/SheetReviewPage";
import WorkbookManagePage from "../pages/admin/manage/WorkbookManagePage";
import VideoManagePage from "../pages/admin/manage/VideoManagePage";

import BoardListPage from "../pages/common/BoardListPage";
import BoardPostPage from "../pages/common/BoardPostPage";
import NotificationsPage from "../pages/common/NotificationsPage";
import PasswordPage from "../pages/common/PasswordPage";
import { NotFoundPage } from "../pages/common/NotFoundPage";

const STAFF = ["대표", "관리자", "조교"] as const;

export const router = createBrowserRouter([

  // 로그인 — 소비자는 한 화면, 직원만 별도 주소.
  {
    path: "/login",
    element: (
      <RedirectIfSignedIn>
        <ConsumerLoginPage />
      </RedirectIfSignedIn>
    ),
  },
  {
    path: "/login/admin",
    element: (
      <RedirectIfSignedIn>
        <AdminLoginPage />
      </RedirectIfSignedIn>
    ),
  },
  // 구 경로(역할별 분리) — 북마크·구 링크를 위해 남겨 둔 리다이렉트.
  { path: "/login/student", element: <Navigate to="/login" replace /> },
  { path: "/login/parent", element: <Navigate to="/login" replace /> },

  // 인증 구역 — 셸이 씌워진다.
  {
    path: "/",
    element: <RequireAuth />,
    children: [
      { index: true, element: <RoleHome /> },

      // ── 학생 ────────────────────────────────────────────────
      {
        path: "student",
        element: <RequireRole roles={["학생"]} />,
        children: [
          { index: true, element: <StudentHomePage /> },
          { path: "grades", element: <StudentGradesPage /> },
          { path: "grades/:examId", element: <StudentGradeDetailPage /> },
          { path: "clinic", element: <StudentClinicPage /> },
          { path: "videos", element: <StudentVideoPage /> },
          { path: "makeup", element: <StudentMakeupPage /> },
          { path: "workbook", element: <StudentWorkbookPage /> },
          // 교재 결제는 예비등록생에게도 열린다 — 등록 가드를 두지 않는다(PRD §4).
          { path: "payments", element: <StudentPaymentPage /> },
        ],
      },

      // ── 학부모 ──────────────────────────────────────────────
      {
        path: "parent",
        element: <RequireRole roles={["학부모"]} />,
        children: [
          { index: true, element: <ParentHomePage /> },
          { path: "grades", element: <ParentGradesPage /> },
          { path: "grades/:examId", element: <ParentGradeDetailPage /> },
          { path: "workbook", element: <ParentWorkbookPage /> },
          { path: "makeup", element: <ParentMakeupPage /> },
          { path: "payments", element: <ParentPaymentPage /> },
        ],
      },

      // ── 관리자 ──────────────────────────────────────────────
      {
        path: "admin",
        element: <RequireRole roles={[...STAFF]} />,
        children: [
          { index: true, element: <AdminDashboardPage /> },

          // 운영
          {
            element: <RequireFeature feature="출결입력" />,
            children: [
              { path: "attendance", element: <AttendancePage /> },
              { path: "attendance/:sessionId", element: <AttendanceSessionPage /> },
            ],
          },
          {
            element: <RequireFeature feature="영상지급관리" />,
            children: [{ path: "makeup", element: <MakeupOpsPage /> }],
          },
          {
            element: <RequireFeature feature="상담기록" />,
            children: [{ path: "counseling", element: <CounselingPage /> }],
          },
          {
            element: <RequireFeature feature="결제확인" />,
            children: [{ path: "payments", element: <PaymentsPage /> }],
          },

          // 관리
          // 권한 매트릭스는 기능 키가 아니라 역할 게이트(대표 전용).
          {
            element: <RequireRole roles={["대표"]} />,
            children: [{ path: "staff", element: <StaffPage /> }],
          },
          {
            element: <RequireFeature feature="계정관리" />,
            children: [
              { path: "accounts", element: <AccountsPage /> },
              { path: "aliases", element: <AliasesPage /> },
              { path: "students/:studentId", element: <StudentDetailPage /> },
              { path: "classes", element: <ClassesPage /> },
            ],
          },
          {
            element: <RequireFeature feature="클리닉배정" />,
            children: [{ path: "clinic", element: <ClinicManagePage /> }],
          },
          {
            element: <RequireFeature feature="성적처리" />,
            children: [
              { path: "exams", element: <ExamsPage /> },
              { path: "exams/:examId", element: <ExamDetailPage /> },
              { path: "exams/:examId/sheets", element: <SheetReviewPage /> },
            ],
          },
          {
            element: <RequireFeature feature="워크북업로드" />,
            children: [{ path: "workbook", element: <WorkbookManagePage /> }],
          },
          {
            element: <RequireFeature feature="영상지급관리" />,
            children: [{ path: "videos", element: <VideoManagePage /> }],
          },
        ],
      },

      // ── 공통(전 역할) ───────────────────────────────────────
      { path: "boards", element: <Navigate to="/boards/공지사항" replace /> },
      { path: "boards/:category", element: <BoardListPage /> },
      { path: "boards/:category/:postId", element: <BoardPostPage /> },
      { path: "notifications", element: <NotificationsPage /> },
      { path: "password", element: <PasswordPage /> },

      { path: "*", element: <NotFoundPage /> },
    ],
  },
]);

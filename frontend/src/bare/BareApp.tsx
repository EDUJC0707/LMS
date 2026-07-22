/**
 * bare 기능 전시 앱(/bare/*) — 디자인 없이 실제로 동작하는 UI.
 * 메뉴는 /api/me 의 role·features 로만 조립한다(PRD §4 메커니즘 시연).
 */
import { Link, NavLink, Route, Routes, useNavigate } from "react-router-dom";

import { MeProvider, useMe } from "./MeContext";
import { api, errMsg } from "./api";
import { PAGES, canAccess } from "./catalog";
import { DebugPanel } from "./ui";
import "./bare.css";

import IndexPage from "./pages/IndexPage";
import LoginPage from "./pages/LoginPage";
import NotificationsPage from "./pages/NotificationsPage";
import PasswordPage from "./pages/PasswordPage";
import { BoardListPage, BoardPostPage } from "./pages/BoardsPage";
import AccountsAdminPage from "./pages/admin/AccountsAdminPage";
import { AttendanceListPage, AttendanceSessionPage } from "./pages/admin/AttendancePage";
import ClinicAdminPage from "./pages/admin/ClinicAdminPage";
import CounselingPage from "./pages/admin/CounselingPage";
import { ExamDetailAdminPage, ExamsAdminPage } from "./pages/admin/ExamsAdminPage";
import MakeupAdminPage from "./pages/admin/MakeupAdminPage";
import StaffMatrixPage from "./pages/admin/StaffMatrixPage";
import WorkbookAdminPage from "./pages/admin/WorkbookAdminPage";
import ParentGradesPage from "./pages/parent/ParentGradesPage";
import ParentHomePage from "./pages/parent/ParentHomePage";
import ParentMakeupPage from "./pages/parent/ParentMakeupPage";
import ParentReportPage from "./pages/parent/ParentReportPage";
import ParentWorkbookPage from "./pages/parent/ParentWorkbookPage";
import StudentClinicPage from "./pages/student/StudentClinicPage";
import StudentGradesPage from "./pages/student/StudentGradesPage";
import StudentHomePage from "./pages/student/StudentHomePage";
import StudentMakeupPage from "./pages/student/StudentMakeupPage";
import StudentReportPage from "./pages/student/StudentReportPage";
import StudentWorkbookPage from "./pages/student/StudentWorkbookPage";

function Header() {
  const { me, loading, refresh } = useMe();
  const navigate = useNavigate();
  const logout = async () => {
    try {
      await api.post("/auth/logout");
      await refresh();
      navigate("/bare/login");
    } catch (e) {
      alert(errMsg(e));
    }
  };
  return (
    <header>
      <h1>
        <Link to="/bare">bare LMS</Link> <small className="muted">기능 전시(디자인 없음)</small>
      </h1>
      <p>
        {loading ? (
          "로그인 상태 확인 중…"
        ) : me ? (
          <>
            <strong>{me.name}</strong> ({me.role})
            {me.role === "학생" && me.student && (
              <span className="muted">
                {" "}
                — {me.student.enrollment_status}
                {me.student.current_class ? ` · ${me.student.current_class}` : ""}
              </span>
            )}
            {me.features && (
              <span className="muted"> — 기능 키 {me.features.length}개: {me.features.join(", ")}</span>
            )}
            {me.must_change_password && (
              <strong className="error"> — 비밀번호 변경 필요</strong>
            )}{" "}
            <button onClick={logout}>로그아웃</button>
          </>
        ) : (
          <>
            비로그인 — <Link to="/bare/login">로그인</Link>
          </>
        )}
      </p>
    </header>
  );
}

function Menu() {
  const { me } = useMe();
  const visible = PAGES.filter((page) => canAccess(me, page));
  return (
    <nav>
      <NavLink to="/bare" end>
        인덱스
      </NavLink>
      {visible.map((page) => (
        <NavLink key={page.path} to={page.path}>
          {page.label}
        </NavLink>
      ))}
    </nav>
  );
}

export default function BareApp() {
  return (
    <MeProvider>
      <div className="bare">
        <Header />
        <Menu />
        <hr />
        <Routes>
          <Route index element={<IndexPage />} />
          <Route path="login" element={<LoginPage />} />
          <Route path="password" element={<PasswordPage />} />
          <Route path="notifications" element={<NotificationsPage />} />
          <Route path="boards/:category" element={<BoardListPage />} />
          <Route path="boards/:category/:postId" element={<BoardPostPage />} />
          <Route path="student/home" element={<StudentHomePage />} />
          <Route path="student/grades" element={<StudentGradesPage />} />
          <Route path="student/grades/:examId" element={<StudentReportPage />} />
          <Route path="student/clinic" element={<StudentClinicPage />} />
          <Route path="student/makeup" element={<StudentMakeupPage />} />
          <Route path="student/workbook" element={<StudentWorkbookPage />} />
          <Route path="parent/home" element={<ParentHomePage />} />
          <Route path="parent/grades" element={<ParentGradesPage />} />
          <Route path="parent/grades/:examId" element={<ParentReportPage />} />
          <Route path="parent/workbook" element={<ParentWorkbookPage />} />
          <Route path="parent/makeup" element={<ParentMakeupPage />} />
          <Route path="admin/attendance" element={<AttendanceListPage />} />
          <Route path="admin/attendance/:sessionId" element={<AttendanceSessionPage />} />
          <Route path="admin/makeup" element={<MakeupAdminPage />} />
          <Route path="admin/exams" element={<ExamsAdminPage />} />
          <Route path="admin/exams/:examId" element={<ExamDetailAdminPage />} />
          <Route path="admin/workbook" element={<WorkbookAdminPage />} />
          <Route path="admin/clinic" element={<ClinicAdminPage />} />
          <Route path="admin/counseling" element={<CounselingPage />} />
          <Route path="admin/accounts" element={<AccountsAdminPage />} />
          <Route path="admin/staff" element={<StaffMatrixPage />} />
          <Route path="*" element={<p className="error">없는 페이지입니다.</p>} />
        </Routes>
        <DebugPanel />
      </div>
    </MeProvider>
  );
}

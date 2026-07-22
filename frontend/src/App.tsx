import { NavLink, Outlet } from "react-router-dom";

// 공용 레이아웃. 역할별 홈(학생/학부모/관리자)이 <Outlet/> 에 렌더된다.
export default function App() {
  return (
    <div>
      <header className="shell-header">
        <div className="shell-brand">
          한종철 과학학원
          <span className="shell-brand-tag">LMS</span>
        </div>
        <nav className="shell-nav" aria-label="역할 선택">
          <NavLink to="/student" className={({ isActive }) => (isActive ? "is-active" : "")}>
            학생
          </NavLink>
          <NavLink to="/parent" className={({ isActive }) => (isActive ? "is-active" : "")}>
            학부모
          </NavLink>
          <NavLink to="/admin" className={({ isActive }) => (isActive ? "is-active" : "")}>
            관리자
          </NavLink>
        </nav>
        <div className="shell-account">
          <span className="shell-avatar" aria-hidden="true">
            서
          </span>
          <span className="shell-account-name">김서연 · 고2 로직엔제 B반</span>
        </div>
      </header>
      <main>
        <Outlet />
      </main>
    </div>
  );
}

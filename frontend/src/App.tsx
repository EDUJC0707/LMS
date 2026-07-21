import { Link, Outlet } from "react-router-dom";

// 공용 레이아웃. 역할별 홈(학생/학부모/관리자)이 <Outlet/> 에 렌더된다.
export default function App() {
  return (
    <div>
      <header>
        <strong>한종철 LMS</strong>
      </header>
      <nav>
        <Link to="/student">학생</Link> | <Link to="/parent">학부모</Link> |{" "}
        <Link to="/admin">관리자</Link>
      </nav>
      <main>
        <Outlet />
      </main>
    </div>
  );
}

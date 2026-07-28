/**
 * 앱 셸 — 좌측 사이드레일(로고 + 역할별 내비) + 상단 바(현재 페이지 · 계정칩 · 로그아웃).
 *
 * 내비 항목은 /api/me 로만 조립한다(auth/nav.ts). 자격 없는 메뉴는
 * 회색 처리하는 게 아니라 **아예 없다**.
 *
 * 상단바 왼쪽은 **지금 보고 있는 화면의 이름**이다(역할 라벨이 아니다 —
 * 그건 계정 칩이 이미 말한다). 이름·아이콘은 레일 항목과 같은 정의에서 온다.
 * 화면당 h1 은 이 이름 하나뿐 — 페이지는 제목 없이 곧장 내용부터 그린다.
 *
 * 반응형: ≥900px 레일 고정 / <900px 상단 가로 탭 스트립.
 * hover 전용 인터랙션 없음 — 전부 탭으로 동작한다.
 */
import { ReactNode } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";

import { RAIL_FOOT, navFor, pageFor } from "../auth/nav";
import { useMe } from "../auth/MeProvider";
import { Button } from "./Button";
import { PageIcon } from "./PageIcon";
import { RoleIcon } from "./RoleIcon";

const linkClass = ({ isActive }: { isActive: boolean }) =>
  `ui-rail__link ${isActive ? "is-active" : ""}`.trim();

export function AppShell({ children }: { children: ReactNode }) {
  const { me, signOut } = useMe();
  const navigate = useNavigate();
  const location = useLocation();

  if (!me) return null;

  const groups = navFor(me);
  const page = pageFor(location.pathname);

  const handleSignOut = async () => {
    await signOut();
    navigate("/login", { replace: true });
  };

  return (
    <div className="ui-shell">
      <nav className="ui-rail on-navy" aria-label="주요 메뉴">
        <div className="ui-rail__brand">
          <img
            className="ui-rail__mark"
            src="/atom-master.png"
            alt=""
            width={32}
            height={32}
          />
          <span className="ui-rail__name">
            <b>한종철 통합과학</b>
            <span className="ui-rail__tag">LMS</span>
          </span>
        </div>

        <div className="ui-rail__scroll">
          {groups.map((group) => (
            <div className="ui-rail__group" key={group.label}>
              <p className="ui-rail__group-label">{group.label}</p>
              {group.items.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.match !== "prefix"}
                  className={linkClass}
                >
                  <PageIcon name={item.icon} size={18} className="ui-rail__icon" />
                  {item.label}
                </NavLink>
              ))}
            </div>
          ))}
        </div>

        <div className="ui-rail__foot">
          <NavLink to={RAIL_FOOT.to} className={linkClass}>
            <PageIcon name={RAIL_FOOT.icon} size={18} className="ui-rail__icon" />
            {RAIL_FOOT.label}
          </NavLink>
        </div>
      </nav>

      <div className="ui-main">
        <header className="ui-topbar">
          {page && (
            <span className="ui-topbar__page">
              <PageIcon name={page.icon} className="ui-topbar__icon" />
              <h1 className="ui-topbar__title">{page.label}</h1>
            </span>
          )}
          <div className="ui-topbar__right">
            <NavLink to="/password" className="ui-accountchip">
              <span className="ui-accountchip__avatar" aria-hidden="true">
                <RoleIcon role={me.role} />
              </span>
              <span className="ui-accountchip__text">
                <span className="ui-accountchip__name">{me.name}</span>
                <span className="ui-accountchip__role">
                  {me.role}
                  {me.student?.current_class ? ` · ${me.student.current_class}` : ""}
                </span>
              </span>
            </NavLink>
            <Button size="sm" variant="ghost" onClick={handleSignOut}>
              로그아웃
            </Button>
          </div>
        </header>

        {/* key: 라우트가 바뀔 때마다 진입 모션을 한 번만 다시 재생한다. */}
        <main className="ui-page" key={location.pathname}>
          {children}
        </main>
      </div>
    </div>
  );
}

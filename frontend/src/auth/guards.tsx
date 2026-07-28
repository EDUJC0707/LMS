/**
 * 라우트 가드. 프런트 가드는 **보조**다 — 실제 강제는 백엔드 퍼미션이 한다.
 * 여기서 하는 일은 "자격 없는 화면을 아예 그리지 않는 것"(PRD §4).
 */
import { ReactNode } from "react";
import { Navigate, Outlet, useLocation } from "react-router-dom";

import { Feature, Role, homePathFor } from "../api/types";
import { AppShell } from "../components/AppShell";
import { Card } from "../components/Card";
import { EmptyState } from "../components/States";
import { Spinner } from "../components/Spinner";
import { useMe } from "./MeProvider";

function Booting() {
  return (
    <div className="ui-loading" role="status" aria-live="polite">
      <Spinner size="lg" />
      <span>불러오는 중…</span>
    </div>
  );
}

/**
 * 로그인 필수 구역. 셸(내비·계정칩)까지 여기서 씌운다.
 * must_change_password 인 사용자는 /password 밖으로 나가지 못한다.
 */
export function RequireAuth() {
  const { me, loading } = useMe();
  const location = useLocation();

  if (loading) return <Booting />;
  if (!me) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  if (me.must_change_password && location.pathname !== "/password") {
    return <Navigate to="/password" replace />;
  }
  return (
    <AppShell>
      <Outlet />
    </AppShell>
  );
}

/** 역할 게이트. 맞지 않으면 자기 홈으로 돌려보낸다(빈 화면·403 대신). */
export function RequireRole({ roles }: { roles: Role[] }) {
  const { me } = useMe();
  if (!me) return null;
  if (!roles.includes(me.role)) return <Navigate to={homePathFor(me.role)} replace />;
  return <Outlet />;
}

/** 직원 기능 키 게이트. 대표는 전권이므로 항상 통과한다(백엔드와 동일 규칙). */
export function RequireFeature({ feature }: { feature: Feature }) {
  const { me, hasFeature } = useMe();
  if (!me) return null;
  if (me.role === "대표" || hasFeature(feature)) return <Outlet />;
  // 화면 이름은 상단바가 이미 그리고 있다(예: "출결 입력"). 여기서는 왜 막혔는지만.
  return (
    <Card>
      <EmptyState
        title={`'${feature}' 권한이 없습니다`}
        description="대표에게 권한을 요청해 주세요"
      />
    </Card>
  );
}

/** 이미 로그인한 사용자는 로그인 화면 대신 자기 홈으로 보낸다. */
export function RedirectIfSignedIn({ children }: { children: ReactNode }) {
  const { me, loading } = useMe();
  if (loading) return <Booting />;
  if (me) {
    return <Navigate to={me.must_change_password ? "/password" : homePathFor(me.role)} replace />;
  }
  return <>{children}</>;
}

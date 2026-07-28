import { Navigate } from "react-router-dom";

import { homePathFor } from "../api/types";
import { useMe } from "../auth/MeProvider";

/** "/" 진입 시 역할별 홈으로 보낸다. */
export function RoleHome() {
  const { me } = useMe();
  if (!me) return null;
  return <Navigate to={homePathFor(me.role)} replace />;
}

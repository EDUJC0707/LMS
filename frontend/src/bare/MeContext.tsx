/**
 * /api/me 상태 컨텍스트 — 상태 기반 노출(PRD §4)의 프런트 관문.
 * 메뉴는 이 응답(role·features·children)으로만 조립한다.
 */
import {
  ReactNode,
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import { api } from "./api";

export interface MeStudent {
  student_id: number;
  enrollment_status: string;
  grade: string;
  current_class: string | null;
}
export interface MeChild {
  student_id: number;
  name: string | null;
  grade: string;
}
export interface Me {
  user_id: number;
  name: string;
  role: string;
  must_change_password: boolean;
  student?: MeStudent | null;
  children?: MeChild[];
  features?: string[];
}

interface MeState {
  me: Me | null;
  loading: boolean;
  refresh: () => Promise<void>;
}

const MeCtx = createContext<MeState>({ me: null, loading: true, refresh: async () => {} });

export function MeProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const { data } = await api.get<Me>("/me");
      setMe(data);
    } catch {
      setMe(null); // 비로그인(403) — 닫힘 상태
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // 부팅 시 CSRF 쿠키 발급(과제 명세) → 로그인 상태 확인
    api
      .get("/auth/csrf")
      .catch(() => undefined)
      .then(() => refresh());
  }, [refresh]);

  const value = useMemo(() => ({ me, loading, refresh }), [me, loading, refresh]);
  return <MeCtx.Provider value={value}>{children}</MeCtx.Provider>;
}

export function useMe(): MeState {
  return useContext(MeCtx);
}

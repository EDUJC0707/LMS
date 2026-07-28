/**
 * 인증 컨텍스트 — /api/me 가 이 앱의 유일한 "무엇을 보여줄지" 근거다(PRD §4).
 *
 * 화면·메뉴는 여기서 나온 role·features·children·student 로만 조립한다.
 * 서버가 내려주지 않은 블록은 만들어내지 않는다.
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

import { fetchMe, logout as postLogout } from "../api/auth";
import { ensureCsrf } from "../api/http";
import { Feature, Me, Role, isStaff } from "../api/types";

export interface MeState {
  /** 로그인 상태면 Me, 아니면 null. */
  me: Me | null;
  /** 최초 /api/me 판정이 끝나기 전에는 true — 이때는 아무 화면도 그리지 않는다. */
  loading: boolean;
  /** 서버에서 다시 읽어온다(로그인 직후·비밀번호 변경 직후 호출). */
  refresh: () => Promise<void>;
  /** 로그아웃 후 컨텍스트를 비운다. */
  signOut: () => Promise<void>;
  /** 직원 기능 키 보유 여부. 학생·학부모는 항상 false. */
  hasFeature: (feature: Feature) => boolean;
  /** 역할 일치 여부. */
  hasRole: (...roles: Role[]) => boolean;
  /** 직원(대표·관리자·조교) 여부. */
  staff: boolean;
}

const MeContext = createContext<MeState | null>(null);

export function MeProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      setMe(await fetchMe());
    } catch {
      setMe(null); // 403 = 비로그인. 에러가 아니라 "닫힌 상태"다.
    } finally {
      setLoading(false);
    }
  }, []);

  const signOut = useCallback(async () => {
    try {
      await postLogout();
    } finally {
      setMe(null);
    }
  }, []);

  useEffect(() => {
    // 부팅 시 CSRF 쿠키 1회 발급 → 로그인 상태 확인.
    void ensureCsrf().then(refresh);
  }, [refresh]);

  const value = useMemo<MeState>(() => {
    const features = me?.features ?? [];
    return {
      me,
      loading,
      refresh,
      signOut,
      hasFeature: (feature) => features.includes(feature),
      hasRole: (...roles) => (me ? roles.includes(me.role) : false),
      staff: me ? isStaff(me.role) : false,
    };
  }, [me, loading, refresh, signOut]);

  return <MeContext.Provider value={value}>{children}</MeContext.Provider>;
}

export function useMe(): MeState {
  const context = useContext(MeContext);
  if (!context) throw new Error("useMe 는 <MeProvider> 안에서만 쓸 수 있습니다.");
  return context;
}

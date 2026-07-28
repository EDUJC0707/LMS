/**
 * 화면이 서버와 대화하는 표준 방법. 모든 페이지는 이 두 훅만 쓴다.
 *
 *   const grades = useApi(() => http.get<Row[]>("/student/grades").then((r) => r.data), []);
 *   if (grades.loading) return <Loading />;
 *   if (grades.error)   return <ErrorState description={grades.error} onRetry={grades.reload} />;
 *
 *   const submit = useApiAction(async (payload: Body) => {
 *     await http.post("/student/clinic", payload);
 *   });
 *   <Button loading={submit.pending} onClick={() => submit.run(payload)}>신청</Button>
 *
 * 규약: 에러는 문자열로만 다룬다(toMessage 가 서버 detail 을 사람 말로 만든다).
 * 화면에서 AxiosError 를 직접 만지지 말 것.
 */
import { DependencyList, useCallback, useEffect, useRef, useState } from "react";

import { toMessage } from "./errors";

export interface ApiState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  /**
   * 처음 불러오는 중(아직 보여줄 데이터가 없음)에만 true.
   *
   * 화면 전체를 로딩으로 덮을지 판단할 때 `loading` 대신 이걸 쓴다. `loading`
   * 으로 덮으면 필터·달 이동처럼 deps 만 바뀌는 재조회에서도 페이지가 통째로
   * 사라졌다 돌아와, 안 바뀌는 영역(제목·마감 카드)까지 깜빡인다.
   * 재조회 중임을 알리려면 `loading` 을 바뀌는 영역에만 쓰라.
   */
  initialLoading: boolean;
  reload: () => Promise<void>;
  /** 낙관적 갱신용 — 서버 재조회 없이 화면 데이터를 갈아끼운다. */
  setData: (next: T | null) => void;
}

/** GET 계열 조회. deps 가 바뀌면 다시 부른다. */
export function useApi<T>(loader: () => Promise<T>, deps: DependencyList): ApiState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  // deps 는 호출부가 넘긴 것을 그대로 쓴다.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const next = await loader();
      if (alive.current) setData(next);
    } catch (caught) {
      if (alive.current) {
        setError(toMessage(caught));
        setData(null);
      }
    } finally {
      if (alive.current) setLoading(false);
    }
  }, deps);

  useEffect(() => {
    void reload();
  }, [reload]);

  return { data, error, loading, initialLoading: loading && data === null, reload, setData };
}

export interface ApiAction<Args extends unknown[], R> {
  run: (...args: Args) => Promise<R | undefined>;
  pending: boolean;
  error: string | null;
  /** 폼을 다시 열 때 등, 이전 에러를 지운다. */
  clearError: () => void;
}

/** POST/PATCH/DELETE 계열 동작. 실패하면 error 에 사람 말 한 문장이 담긴다. */
export function useApiAction<Args extends unknown[], R>(
  action: (...args: Args) => Promise<R>,
  options?: { onSuccess?: (result: R) => void },
): ApiAction<Args, R> {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const onSuccess = options?.onSuccess;

  const run = useCallback(
    async (...args: Args) => {
      setPending(true);
      setError(null);
      try {
        const result = await action(...args);
        onSuccess?.(result);
        return result;
      } catch (caught) {
        setError(toMessage(caught));
        return undefined;
      } finally {
        setPending(false);
      }
    },
    // action 이 매 렌더 새로 만들어지는 경우가 많아 의존성에서 뺀다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [onSuccess],
  );

  return { run, pending, error, clearError: () => setError(null) };
}

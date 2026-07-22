/** bare 공용 부품 — 로딩 훅·메시지·디버그 패널(JSON 원문 접이식). */
import { useCallback, useEffect, useState, useSyncExternalStore } from "react";

import { apiLogEntries, apiLogVersion, errMsg, subscribeApiLog } from "./api";

export const WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"];

export function weekdayName(no: number | null | undefined): string {
  return no === null || no === undefined ? "-" : (WEEKDAYS[no] ?? String(no));
}

/** 단순 로더 훅 — deps 변경 시 재조회. reload 로 수동 갱신. */
export function useLoad<T>(loader: () => Promise<T>, deps: readonly unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await loader());
    } catch (e) {
      setError(errMsg(e));
      setData(null);
    } finally {
      setLoading(false);
    }
  }, deps as unknown[]);
  useEffect(() => {
    void reload();
  }, [reload]);
  return { data, setData, error, loading, reload };
}

/** 에러(빨강)·성공(초록) 한 줄 메시지 — 폼 근처에 사람이 읽게 표시. */
export function Msg({ error, ok }: { error?: string | null; ok?: string | null }) {
  if (error) return <p className="error">{error}</p>;
  if (ok) return <p className="ok">{ok}</p>;
  return null;
}

/** 페이지 하단 디버그 — 최근 API 요청/응답 원문(JSON) 접이식 표시. */
export function DebugPanel() {
  useSyncExternalStore(subscribeApiLog, apiLogVersion);
  const entries = apiLogEntries();
  return (
    <details className="debug">
      <summary>디버그 — API 응답 원문 (최근 {entries.length}건)</summary>
      {entries.map((entry, index) => (
        <details key={`${entry.at}-${index}`}>
          <summary>
            {entry.at} {entry.method} {entry.url} → {String(entry.status)}
          </summary>
          <pre>{JSON.stringify(entry.data, null, 2)}</pre>
        </details>
      ))}
    </details>
  );
}

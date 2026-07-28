/**
 * 토스트. 규약:
 * - 성공은 조용히 넘어간다. 화면에 결과가 이미 보이면 토스트를 띄우지 않는다.
 * - 실패, 비동기 결과, "되돌리기"가 필요한 동작에만 쓴다.
 * - 새 토스트가 떠도 기존 토스트는 자리를 옮기지 않는다(우하단 고정 스택).
 *
 *   const toast = useToast();
 *   toast.show("출결을 저장했습니다.", { action: { label: "되돌리기", onClick: undo } });
 *   toast.error("승인하지 못했습니다. 잠시 후 다시 시도해 주세요.");
 */
import {
  ReactNode,
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
} from "react";

export type ToastTone = "neutral" | "success" | "danger";

export interface ToastAction {
  label: string;
  onClick: () => void;
}

interface ToastItem {
  id: number;
  text: string;
  tone: ToastTone;
  action?: ToastAction;
}

export interface ToastApi {
  show: (text: string, options?: { tone?: ToastTone; action?: ToastAction; ms?: number }) => void;
  error: (text: string) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const seq = useRef(0);

  const dismiss = useCallback((id: number) => {
    setItems((prev) => prev.filter((item) => item.id !== id));
  }, []);

  const show = useCallback<ToastApi["show"]>(
    (text, options) => {
      const id = ++seq.current;
      const item: ToastItem = { id, text, tone: options?.tone ?? "neutral", action: options?.action };
      setItems((prev) => [...prev, item]);
      window.setTimeout(() => dismiss(id), options?.ms ?? (options?.action ? 8000 : 4000));
    },
    [dismiss],
  );

  const api = useMemo<ToastApi>(
    () => ({ show, error: (text) => show(text, { tone: "danger", ms: 6000 }) }),
    [show],
  );

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="ui-toaster" role="status" aria-live="polite">
        {items.map((item) => (
          <div
            key={item.id}
            className={`ui-toast ${item.tone !== "neutral" ? `ui-toast--${item.tone}` : ""}`.trim()}
          >
            <span className="ui-toast__text">{item.text}</span>
            {item.action && (
              <button
                type="button"
                className="ui-toast__action"
                onClick={() => {
                  item.action!.onClick();
                  dismiss(item.id);
                }}
              >
                {item.action.label}
              </button>
            )}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  const context = useContext(ToastContext);
  if (!context) throw new Error("useToast 는 <ToastProvider> 안에서만 쓸 수 있습니다.");
  return context;
}

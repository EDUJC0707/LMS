/**
 * 모달. 네이티브 <dialog> 를 쓴다 — 포커스 트랩·Esc 닫기·backdrop 이 공짜다.
 * 되돌릴 수 있는 동작에는 모달을 쓰지 않는다(바로 실행 + 되돌리기 토스트).
 */
import { ReactNode, useEffect, useRef } from "react";

export interface ModalProps {
  open: boolean;
  onClose: () => void;
  title: string;
  /** 하단 버튼 줄. 오른쪽 정렬된다. */
  footer?: ReactNode;
  /** 표가 들어가는 넓은 모달. */
  wide?: boolean;
  children: ReactNode;
}

export function Modal({ open, onClose, title, footer, wide = false, children }: ModalProps) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      className={`ui-modal ${wide ? "ui-modal--wide" : ""}`.trim()}
      aria-labelledby="ui-modal-title"
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClick={(event) => {
        // backdrop(=dialog 자신) 클릭으로 닫기. 내용 클릭은 통과.
        if (event.target === ref.current) onClose();
      }}
    >
      <header className="ui-modal__head">
        <h2 className="ui-modal__title" id="ui-modal-title">
          {title}
        </h2>
        <button type="button" className="ui-modal__close" onClick={onClose} aria-label="닫기">
          ✕
        </button>
      </header>
      <div className="ui-modal__body">{children}</div>
      {footer && <footer className="ui-modal__foot">{footer}</footer>}
    </dialog>
  );
}

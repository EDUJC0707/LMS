import { ButtonHTMLAttributes, ReactNode, forwardRef } from "react";

import { Spinner } from "./Spinner";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";

export interface ButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "children"> {
  /** primary=1차 액션(네이비 채움) · secondary=보조 · ghost=표 안 인라인 · danger=삭제/거절 */
  variant?: ButtonVariant;
  size?: "md" | "sm";
  /** 처리 중 — 라벨은 유지하고 앞에 스피너가 붙는다. 자동으로 disabled 된다. */
  loading?: boolean;
  /** 컨테이너 폭을 꽉 채운다(로그인 폼 등). */
  block?: boolean;
  children: ReactNode;
}

/**
 * 버튼. type 기본값은 "button" — 폼 안에서 의도치 않은 submit 을 막는다.
 * 제출 버튼에는 반드시 type="submit" 을 명시할 것.
 */
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", loading = false, block = false, children, ...rest },
  ref,
) {
  const classes = [
    "ui-btn",
    `ui-btn--${variant}`,
    size === "sm" ? "ui-btn--sm" : "",
    block ? "ui-btn--block" : "",
    rest.className ?? "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <button
      {...rest}
      ref={ref}
      type={rest.type ?? "button"}
      className={classes}
      disabled={rest.disabled || loading}
      aria-busy={loading || undefined}
    >
      {loading && <Spinner size="sm" className="ui-btn__spinner" />}
      {children}
    </button>
  );
});

/**
 * 폼 부품. 규약 세 가지:
 * 1) 라벨은 항상 입력 위에 보인다. placeholder 를 라벨로 쓰지 않는다.
 * 2) 도움말 자리는 비어 있어도 높이를 차지한다 — 에러가 떠도 아래가 안 밀린다.
 * 3) 테두리 두께는 모든 상태에서 1px 고정. 포커스는 outline 으로만 표시한다.
 */
import {
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
  forwardRef,
  useId,
} from "react";

export interface FieldProps {
  label: string;
  /** 평상시 도움말. error 가 있으면 error 로 대체된다. */
  hint?: ReactNode;
  /** 에러 문구 — 서버 detail 을 그대로 넣어도 된다. */
  error?: string | null;
  required?: boolean;
  /** <Input>·<Select>·<Textarea> 또는 커스텀 컨트롤. id/aria 는 자동 연결된다. */
  children: (props: {
    id: string;
    "aria-describedby": string;
    "aria-invalid": boolean | undefined;
    required: boolean;
  }) => ReactNode;
}

/** 라벨 + 컨트롤 + 도움말/에러 한 세트. */
export function Field({ label, hint, error, required = false, children }: FieldProps) {
  const id = useId();
  const helpId = `${id}-help`;
  return (
    <div className="ui-field">
      <label className="ui-field__label" htmlFor={id}>
        {label}
        {required && (
          <span className="ui-field__req" aria-hidden="true">
            *
          </span>
        )}
      </label>
      {children({
        id,
        "aria-describedby": helpId,
        "aria-invalid": error ? true : undefined,
        required,
      })}
      <p
        id={helpId}
        className={`ui-field__help ${error ? "ui-field__help--error" : ""}`.trim()}
        role={error ? "alert" : undefined}
      >
        {error ?? hint ?? ""}
      </p>
    </div>
  );
}

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  function Input({ className = "", ...rest }, ref) {
    return <input {...rest} ref={ref} className={`ui-input ${className}`.trim()} />;
  },
);

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(
  function Select({ className = "", children, ...rest }, ref) {
    return (
      <select {...rest} ref={ref} className={`ui-select ${className}`.trim()}>
        {children}
      </select>
    );
  },
);

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(
  function Textarea({ className = "", ...rest }, ref) {
    return <textarea {...rest} ref={ref} className={`ui-textarea ${className}`.trim()} />;
  },
);

export interface CheckboxProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "type"> {
  label: ReactNode;
}

/** 체크박스. 라벨 전체가 히트 영역이다(44px 높이). */
export function Checkbox({ label, className = "", ...rest }: CheckboxProps) {
  return (
    <label className={`ui-check ${className}`.trim()}>
      <input {...rest} type="checkbox" />
      <span className="ui-check__label">{label}</span>
    </label>
  );
}

export interface RadioProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "type"> {
  label: ReactNode;
}

/** 라디오. 같은 그룹은 name 을 같게 준다. */
export function Radio({ label, className = "", ...rest }: RadioProps) {
  return (
    <label className={`ui-check ${className}`.trim()}>
      <input {...rest} type="radio" />
      <span className="ui-check__label">{label}</span>
    </label>
  );
}

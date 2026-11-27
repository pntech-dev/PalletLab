import type { InputHTMLAttributes, ReactNode } from "react";

type Props = Omit<InputHTMLAttributes<HTMLInputElement>, "type"> & {
  label?: ReactNode;
};

/** Native checkbox with the shared Figma design-system appearance. */
export function Checkbox({ label, className = "", ...props }: Props) {
  const control = (
    <span className={["ui-checkbox", label === undefined ? className : ""].filter(Boolean).join(" ")}>
      <input {...props} type="checkbox" />
      <span className="ui-checkbox-box" aria-hidden="true">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M4 12 9 17 20 6" />
        </svg>
      </span>
    </span>
  );
  if (label === undefined) return control;
  return (
    <label className={["ui-checkbox-label", className].filter(Boolean).join(" ")}>
      {control}
      <span>{label}</span>
    </label>
  );
}

import type { InputHTMLAttributes, ReactNode } from "react";

type Props = Omit<InputHTMLAttributes<HTMLInputElement>, "type"> & {
  label?: ReactNode;
};

/** Native radio control with the shared Figma design-system appearance. */
export function Radio({ label, className = "", ...props }: Props) {
  const control = (
    <span className={["ui-radio", label === undefined ? className : ""].filter(Boolean).join(" ")}>
      <input {...props} type="radio" />
      <span className="ui-radio-circle" aria-hidden="true" />
    </span>
  );
  if (label === undefined) return control;
  return (
    <label className={["ui-radio-label", className].filter(Boolean).join(" ")}>
      {control}
      <span>{label}</span>
    </label>
  );
}

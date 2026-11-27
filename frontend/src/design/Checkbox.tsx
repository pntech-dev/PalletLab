import type { InputHTMLAttributes, ReactNode } from "react";
import { Check } from "lucide-react";

type Props = Omit<InputHTMLAttributes<HTMLInputElement>, "type"> & {
  label?: ReactNode;
};

/** Native checkbox with the shared Figma design-system appearance. */
export function Checkbox({ label, className = "", ...props }: Props) {
  const control = (
    <span className={["ui-checkbox", label === undefined ? className : ""].filter(Boolean).join(" ")}>
      <input {...props} type="checkbox" />
      <span className="ui-checkbox-box" aria-hidden="true"><Check size={16} /></span>
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

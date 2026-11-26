import type { InputHTMLAttributes } from "react";
import { Check } from "lucide-react";

type Props = Omit<InputHTMLAttributes<HTMLInputElement>, "type">;

/** Native checkbox with the shared design-system appearance. */
export function Checkbox(props: Props) {
  return <span className="ui-checkbox">
    <input {...props} type="checkbox" />
    <span className="ui-checkbox-box" aria-hidden="true"><Check size={16} /></span>
  </span>;
}

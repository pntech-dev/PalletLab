import type { HTMLAttributes, ReactNode } from "react";
import { BadgeAlert, Check, Info, TriangleAlert } from "lucide-react";

export type MessageBoxVariant = "info" | "warning" | "error" | "success";

type Props = Omit<HTMLAttributes<HTMLDivElement>, "title"> & {
  variant?: MessageBoxVariant;
  title: ReactNode;
  text?: ReactNode;
};

const ICONS = {
  info: Info,
  warning: TriangleAlert,
  error: BadgeAlert,
  success: Check,
} satisfies Record<MessageBoxVariant, typeof Info>;

/** Reusable status/alert message banner aligned with the Figma Messages Boxes variants. */
export function MessageBox({
  variant = "info",
  title,
  text,
  className = "",
  children,
  ...props
}: Props) {
  const Icon = ICONS[variant];
  const body = text ?? children;
  return (
    <div className={["ui-message", `ui-message--${variant}`, className].filter(Boolean).join(" ")} {...props}>
      <Icon key={variant} size={24} aria-hidden="true" />
      <div>
        <strong>{title}</strong>
        {body ? <p>{body}</p> : null}
      </div>
    </div>
  );
}

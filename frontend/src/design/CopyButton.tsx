import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type ButtonHTMLAttributes,
  type ReactNode,
} from "react";
import { Check, Copy } from "lucide-react";
import { Button } from "./Button";

const CopyContext = createContext(false);

type CopyButtonProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, "content" | "onCopy"> & {
  content: string;
  variant?: "primary" | "secondary" | "tertiary" | "ghost" | "danger";
  delay?: number;
  copiedAriaLabel?: string;
  onCopy?: (content: string) => Promise<boolean> | boolean;
  onCopiedChange?: (copied: boolean) => void;
};

/** Button with animated copy-to-checkmark feedback matching Animate UI CopyButton behavior. */
export function CopyButton({
  content,
  variant = "ghost",
  delay = 2500,
  copiedAriaLabel = "Скопировано в буфер обмена",
  onCopy,
  onCopiedChange,
  onClick,
  disabled,
  className = "",
  "aria-label": ariaLabel,
  children,
  ...props
}: CopyButtonProps) {
  const [copied, setCopied] = useState(false);
  const timerRef = useRef<number | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    };
  }, []);

  async function handleClick(event: React.MouseEvent<HTMLButtonElement>) {
    onClick?.(event);
    if (event.defaultPrevented || disabled || !content) return;

    let ok = false;
    try {
      if (onCopy) {
        ok = await onCopy(content);
      } else if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(content);
        ok = true;
      }
    } catch {
      ok = false;
    }

    if (!ok || !mountedRef.current) return;
    if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    setCopied(true);
    onCopiedChange?.(true);
    timerRef.current = window.setTimeout(() => {
      timerRef.current = null;
      if (!mountedRef.current) return;
      setCopied(false);
      onCopiedChange?.(false);
    }, delay);
  }

  return (
    <CopyContext.Provider value={copied}>
      <Button
        variant={variant}
        disabled={disabled}
        data-copied={copied ? "true" : undefined}
        aria-label={copied ? copiedAriaLabel : ariaLabel}
        className={["ui-copy-button", copied ? "is-copied" : "", className].filter(Boolean).join(" ")}
        onClick={(event) => void handleClick(event)}
        {...props}
      >
        {children ?? <CopyButtonIcon />}
      </Button>
    </CopyContext.Provider>
  );
}

/** Animated icon slot swapping between idle copy icon and copied checkmark inside CopyButton. */
export function CopyButtonIcon({
  icon = <Copy size={16} aria-hidden="true" />,
  copiedIcon = <Check size={16} aria-hidden="true" />,
}: {
  icon?: ReactNode;
  copiedIcon?: ReactNode;
}) {
  useContext(CopyContext);
  return (
    <span className="ui-copy-icon-stack" aria-hidden="true">
      <span className="ui-copy-icon ui-copy-icon--idle">{icon}</span>
      <span className="ui-copy-icon ui-copy-icon--copied">{copiedIcon}</span>
    </span>
  );
}

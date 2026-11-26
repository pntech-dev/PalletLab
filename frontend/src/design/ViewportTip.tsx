type Props = { text: string; canExit: boolean };

/** Context help follows the pointer but never intercepts viewport input. */
export function ViewportTip({ text, canExit }: Props) {
  const [message, ...details] = text.split("\n");
  const rightClick = details.join(" ").replace(/^ПКМ\s*[—–-]\s*/, "");
  return <>
    <span className="viewport-hint-message">{message}</span>
    {(rightClick || canExit) && <span className="viewport-hint-shortcuts">
      {rightClick && <span><kbd>ПКМ</kbd> — {rightClick}</span>}
      {canExit && <span><kbd>Esc</kbd> — выход</span>}
    </span>}
  </>;
}

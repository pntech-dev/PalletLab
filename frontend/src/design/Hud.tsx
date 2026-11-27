import type { ReactNode, SyntheticEvent } from "react";
import { Info } from "lucide-react";

type Props = { title: ReactNode; children: ReactNode; actions: ReactNode; className?: string };

function stopViewportPropagation(event: SyntheticEvent) {
  event.stopPropagation();
}

/** Shared surface for contextual 3D editing tools. */
export function Hud({ title, children, actions, className = "" }: Props) {
  return <div
    className={`manual-hud ${className}`}
    onPointerDown={stopViewportPropagation}
    onPointerUp={stopViewportPropagation}
    onPointerCancel={stopViewportPropagation}
    onMouseDown={stopViewportPropagation}
    onTouchStart={stopViewportPropagation}
    onWheel={stopViewportPropagation}
    onClick={stopViewportPropagation}
    onContextMenu={stopViewportPropagation}
  >
    <strong className="hud-title">{title}</strong>
    <div className="hud-content">{children}</div>
    <div className="hud-actions">{actions}</div>
  </div>;
}

export function HudHint({ id, children }: { id?: string; children: ReactNode }) {
  return <p className="hud-hint" id={id}><Info size={16} aria-hidden="true" /><span>{children}</span></p>;
}

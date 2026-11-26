import type { ReactNode } from "react";

type Props = { title: ReactNode; children: ReactNode; actions: ReactNode; className?: string };

/** Shared surface for contextual 3D editing tools. */
export function Hud({ title, children, actions, className = "" }: Props) {
  return <div className={`manual-hud ${className}`}>
    <strong className="hud-title">{title}</strong>
    <div className="hud-content">{children}</div>
    <div className="hud-actions">{actions}</div>
  </div>;
}

import { useLayoutEffect, useRef } from "react";

const EXPAND_DURATION_MS = 380;
const COLLAPSE_DURATION_MS = 320;
const BOUNCY_SPRING = sampleSpring(430, 19, EXPAND_DURATION_MS, 28);
const COLLAPSE_SPRING = sampleSpring(460, 28, COLLAPSE_DURATION_MS, 24);

export function sampleSpring(stiffness: number, damping: number, durationMs: number, steps = 28): number[] {
  const dt = durationMs / 1000 / steps;
  let position = 0;
  let velocity = 0;
  const samples = [0];
  for (let i = 1; i < steps; i += 1) {
    const accel = (1 - position) * stiffness - velocity * damping;
    velocity += accel * dt;
    position += velocity * dt;
    samples.push(position);
  }
  samples.push(1);
  return samples;
}

/** Label wrapper whose width, gap, and opacity spring cleanly on expand/collapse. */
export function ExpandableLabel({ text, expanded, animate = true }: { text: string; expanded: boolean; animate?: boolean }) {
  const wrapRef = useRef<HTMLSpanElement | null>(null);
  const innerRef = useRef<HTMLSpanElement | null>(null);
  const animRef = useRef<Animation | null>(null);
  const prevExpandedRef = useRef<boolean | null>(null);

  useLayoutEffect(() => {
    const wrap = wrapRef.current;
    const inner = innerRef.current;
    if (!wrap || !inner) return;

    const applyRestStyles = (isExpanded: boolean) => {
      wrap.style.width = isExpanded ? "auto" : "0px";
      wrap.style.marginLeft = isExpanded ? "var(--space-2)" : "0px";
      wrap.style.opacity = isExpanded ? "1" : "0";
    };

    if (!animate) {
      animRef.current?.cancel();
      animRef.current = null;
      prevExpandedRef.current = expanded;
      applyRestStyles(expanded);
      return;
    }

    if (prevExpandedRef.current === null) {
      prevExpandedRef.current = expanded;
      applyRestStyles(expanded);
      return;
    }

    if (prevExpandedRef.current === expanded) {
      if (!animRef.current) applyRestStyles(expanded);
      return;
    }

    prevExpandedRef.current = expanded;
    const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    animRef.current?.cancel();
    animRef.current = null;

    if (reducedMotion) {
      applyRestStyles(expanded);
      return;
    }

    const computed = window.getComputedStyle(wrap);
    const fromWidth = parseFloat(computed.width) || 0;
    const fromMargin = parseFloat(computed.marginLeft) || 0;
    const fromOpacity = Number(computed.opacity);
    const startOpacity = Number.isFinite(fromOpacity) ? fromOpacity : (expanded ? 0 : 1);

    const targetWidth = expanded ? Math.ceil(inner.scrollWidth) : 0;
    const targetMargin = expanded ? 8 : 0;
    const targetOpacity = expanded ? 1 : 0;
    const curve = expanded ? BOUNCY_SPRING : COLLAPSE_SPRING;
    const duration = expanded ? EXPAND_DURATION_MS : COLLAPSE_DURATION_MS;

    const keyframes: Keyframe[] = curve.map((p) => {
      const width = Math.max(0, fromWidth + (targetWidth - fromWidth) * p);
      const marginLeft = Math.max(0, fromMargin + (targetMargin - fromMargin) * p);
      const opacity = expanded
        ? Math.max(0, Math.min(1, startOpacity + (targetOpacity - startOpacity) * Math.min(1, p * 1.45)))
        : Math.max(0, Math.min(1, startOpacity * Math.max(0, 1 - p * 1.6)));
      return {
        width: `${width.toFixed(2)}px`,
        marginLeft: `${marginLeft.toFixed(2)}px`,
        opacity,
      };
    });

    const anim = wrap.animate(keyframes, {
      duration,
      easing: "linear",
      fill: "forwards",
    });
    animRef.current = anim;
    anim.onfinish = () => {
      if (animRef.current !== anim) return;
      animRef.current = null;
      anim.cancel();
      applyRestStyles(expanded);
    };
  }, [animate, expanded, text]);

  return (
    <span ref={wrapRef} className="toolbar-label-wrap" aria-hidden={!expanded}>
      <span ref={innerRef} className="toolbar-label">{text}</span>
    </span>
  );
}

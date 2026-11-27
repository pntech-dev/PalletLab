import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";

export type TooltipSide = "top" | "bottom";
export type TooltipAlign = "start" | "center" | "end";

type ActiveTooltip = {
  id: string;
  content: string;
  trigger: HTMLElement;
  side: TooltipSide;
  sideOffset: number;
  align: TooltipAlign;
  alignOffset: number;
};

type TooltipContextValue = {
  delay: number;
  activeId: string | null;
  show: (item: ActiveTooltip, immediate?: boolean) => void;
  updateContent: (id: string, content: string) => void;
  hide: (id: string, immediate?: boolean) => void;
};

const TooltipContext = createContext<TooltipContextValue | null>(null);

const GLIDE_DURATION_MS = 220;
const GROUP_CLOSE_GRACE_MS = 90;
const GLIDE_EASING = "cubic-bezier(0.2, 0.8, 0.2, 1)";

function computePosition(item: ActiveTooltip, tip: HTMLElement) {
  const rect = item.trigger.getBoundingClientRect();
  const margin = 8;
  const tipWidth = tip.offsetWidth;
  const tipHeight = tip.offsetHeight;

  let top = item.side === "bottom"
    ? rect.bottom + item.sideOffset
    : rect.top - item.sideOffset - tipHeight;
  let resolvedSide = item.side;
  if (item.side === "bottom" && top + tipHeight > window.innerHeight - margin) {
    const above = rect.top - item.sideOffset - tipHeight;
    if (above >= margin) {
      top = above;
      resolvedSide = "top";
    }
  } else if (item.side === "top" && top < margin) {
    const below = rect.bottom + item.sideOffset;
    if (below + tipHeight <= window.innerHeight - margin) {
      top = below;
      resolvedSide = "bottom";
    }
  }
  top = Math.max(margin, Math.min(top, window.innerHeight - tipHeight - margin));

  let rawLeft = rect.left + rect.width / 2 - tipWidth / 2;
  if (item.align === "start") rawLeft = rect.left;
  else if (item.align === "end") rawLeft = rect.right - tipWidth;
  rawLeft += item.alignOffset;
  const left = Math.max(margin, Math.min(rawLeft, window.innerWidth - tipWidth - margin));

  const triggerCenter = rect.left + rect.width / 2;
  const originX = Math.max(8, Math.min(tipWidth - 8, triggerCenter - left));
  const originY = resolvedSide === "bottom" ? 0 : tipHeight;

  return {
    top,
    left,
    width: tipWidth,
    height: tipHeight,
    side: resolvedSide,
    transformOrigin: `${originX.toFixed(1)}px ${originY.toFixed(1)}px`,
  };
}

/** Coordinates shared tooltip state and smooth compositor glide/scale transitions across triggers. */
export function TooltipProvider({
  delay = 0,
  children,
}: {
  delay?: number;
  children: ReactNode;
}) {
  const [active, setActive] = useState<ActiveTooltip | null>(null);
  const [displayedText, setDisplayedText] = useState("");
  const openTimerRef = useRef<number | null>(null);
  const closeTimerRef = useRef<number | null>(null);
  const tipRef = useRef<HTMLDivElement | null>(null);
  const glideAnimRef = useRef<Animation | null>(null);
  const prevBoxRef = useRef<{
    id: string;
    top: number;
    left: number;
    width: number;
    height: number;
  } | null>(null);
  const activeIdRef = useRef<string | null>(null);

  const clearTimers = useCallback(() => {
    if (openTimerRef.current !== null) {
      window.clearTimeout(openTimerRef.current);
      openTimerRef.current = null;
    }
    if (closeTimerRef.current !== null) {
      window.clearTimeout(closeTimerRef.current);
      closeTimerRef.current = null;
    }
  }, []);

  useEffect(() => clearTimers, [clearTimers]);

  const show = useCallback((item: ActiveTooltip, immediate = false) => {
    clearTimers();
    if (activeIdRef.current === item.id) return;
    const waitMs = immediate || activeIdRef.current !== null ? 0 : delay;
    if (waitMs <= 0) {
      activeIdRef.current = item.id;
      setDisplayedText(item.content);
      setActive(item);
      return;
    }
    openTimerRef.current = window.setTimeout(() => {
      openTimerRef.current = null;
      activeIdRef.current = item.id;
      setDisplayedText(item.content);
      setActive(item);
    }, waitMs);
  }, [clearTimers, delay]);

  const updateContent = useCallback((id: string, content: string) => {
    if (activeIdRef.current !== id) return;
    setDisplayedText((current) => (current === content ? current : content));
    setActive((current) => (current && current.id === id && current.content !== content ? { ...current, content } : current));
  }, []);

  const hide = useCallback((id: string, immediate = false) => {
    if (openTimerRef.current !== null) {
      window.clearTimeout(openTimerRef.current);
      openTimerRef.current = null;
    }
    if (activeIdRef.current !== id && activeIdRef.current !== null) return;
    if (closeTimerRef.current !== null) {
      window.clearTimeout(closeTimerRef.current);
      closeTimerRef.current = null;
    }
    const commitHide = () => {
      activeIdRef.current = null;
      setActive(null);
    };
    if (immediate) {
      commitHide();
      return;
    }
    closeTimerRef.current = window.setTimeout(() => {
      closeTimerRef.current = null;
      commitHide();
    }, GROUP_CLOSE_GRACE_MS);
  }, []);

  useEffect(() => {
    if (!active) return;
    const hideNow = () => {
      clearTimers();
      activeIdRef.current = null;
      setActive(null);
    };
    const onEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") hideNow();
    };
    window.addEventListener("keydown", onEscape, true);
    window.addEventListener("resize", hideNow);
    window.addEventListener("scroll", hideNow, true);
    window.addEventListener("blur", hideNow);
    return () => {
      window.removeEventListener("keydown", onEscape, true);
      window.removeEventListener("resize", hideNow);
      window.removeEventListener("scroll", hideNow, true);
      window.removeEventListener("blur", hideNow);
    };
  }, [active, clearTimers]);

  useLayoutEffect(() => {
    const tip = tipRef.current;
    if (!tip) return;
    let enterFrame = 0;
    const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;

    if (!active) {
      prevBoxRef.current = null;
      glideAnimRef.current?.cancel();
      glideAnimRef.current = null;
      tip.classList.remove("is-open");
      return;
    }

    const next = computePosition(active, tip);
    tip.style.top = `${next.top}px`;
    tip.style.left = `${next.left}px`;
    tip.style.transformOrigin = next.transformOrigin;
    const prev = prevBoxRef.current;
    prevBoxRef.current = {
      id: active.id,
      top: next.top,
      left: next.left,
      width: next.width,
      height: next.height,
    };

    glideAnimRef.current?.cancel();
    glideAnimRef.current = null;

    if (prev && prev.id !== active.id) {
      tip.classList.add("is-open");
      if (!reducedMotion) {
        const dx = prev.left - next.left;
        const dy = prev.top - next.top;
        const sx = prev.width / Math.max(1, next.width);
        const sy = prev.height / Math.max(1, next.height);
        glideAnimRef.current = tip.animate(
          [
            { transform: `translate3d(${dx.toFixed(2)}px, ${dy.toFixed(2)}px, 0) scale(${sx.toFixed(4)}, ${sy.toFixed(4)})` },
            { transform: "translate3d(0px, 0px, 0) scale(1, 1)" },
          ],
          {
            duration: GLIDE_DURATION_MS,
            easing: GLIDE_EASING,
          },
        );
      }
      return;
    }

    if (!prev) {
      if (reducedMotion) {
        tip.classList.add("is-open");
        return;
      }
      tip.classList.remove("is-open");
      void tip.offsetWidth;
      enterFrame = window.requestAnimationFrame(() => {
        enterFrame = 0;
        if (activeIdRef.current !== active.id) return;
        tip.classList.add("is-open");
      });
    }

    return () => {
      if (enterFrame !== 0) window.cancelAnimationFrame(enterFrame);
    };
  }, [active, displayedText]);

  const value = useMemo<TooltipContextValue>(() => ({
    delay,
    activeId: active?.id ?? null,
    show,
    updateContent,
    hide,
  }), [active?.id, delay, hide, show, updateContent]);

  return (
    <TooltipContext.Provider value={value}>
      {children}
      {createPortal(
        <div
          ref={tipRef}
          id={active?.id}
          role="tooltip"
          aria-hidden={!active}
          className="ui-tooltip"
          data-side={active?.side ?? "bottom"}
        >
          {displayedText}
        </div>,
        document.body,
      )}
    </TooltipContext.Provider>
  );
}

type TooltipProps = {
  content: string;
  side?: TooltipSide;
  sideOffset?: number;
  align?: TooltipAlign;
  alignOffset?: number;
  className?: string;
  children: ReactNode;
};

/** Hover and focus tooltip trigger connected to TooltipProvider. */
export function Tooltip({
  content,
  side = "bottom",
  sideOffset = 6,
  align = "center",
  alignOffset = 0,
  className = "",
  children,
}: TooltipProps) {
  const context = useContext(TooltipContext);
  const triggerRef = useRef<HTMLSpanElement | null>(null);
  const tooltipId = useId();
  const isOpen = context?.activeId === tooltipId;

  const triggerShow = useCallback((immediate = false) => {
    if (!context || !triggerRef.current) return;
    context.show({
      id: tooltipId,
      content,
      trigger: triggerRef.current,
      side,
      sideOffset,
      align,
      alignOffset,
    }, immediate);
  }, [align, alignOffset, content, context, side, sideOffset, tooltipId]);

  useEffect(() => {
    if (isOpen) context?.updateContent(tooltipId, content);
  }, [content, context, isOpen, tooltipId]);

  return (
    <span
      ref={triggerRef}
      className={["ui-tooltip-trigger", className].filter(Boolean).join(" ")}
      aria-describedby={isOpen ? tooltipId : undefined}
      onPointerEnter={(event) => {
        if (event.pointerType === "touch") return;
        triggerShow(false);
      }}
      onPointerLeave={() => context?.hide(tooltipId, false)}
      onPointerDown={() => context?.hide(tooltipId, true)}
      onFocus={(event) => {
        if (event.target instanceof Element && event.target.matches(":focus-visible")) {
          triggerShow(true);
        }
      }}
      onBlur={() => context?.hide(tooltipId, true)}
    >
      {children}
    </span>
  );
}

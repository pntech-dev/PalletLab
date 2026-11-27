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
import {
  computeTooltipBounds,
  placeTooltip,
  type TooltipAlign,
  type TooltipSide,
} from "./tooltipPlacement";

export type { TooltipAlign, TooltipSide } from "./tooltipPlacement";

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

function getViewportBounds(trigger: HTMLElement) {
  const viewport = trigger.closest<HTMLElement>(".viewport");
  if (!viewport) {
    return computeTooltipBounds(window.innerWidth, window.innerHeight, null);
  }
  const rect = viewport.getBoundingClientRect();
  const styles = getComputedStyle(viewport);
  return computeTooltipBounds(window.innerWidth, window.innerHeight, {
    rect,
    rightInset: Number.parseFloat(styles.getPropertyValue("--viewport-right-inset")) || 0,
    bottomInset: Number.parseFloat(styles.getPropertyValue("--viewport-bottom-inset")) || 0,
  });
}

function computePosition(item: ActiveTooltip, tip: HTMLElement) {
  const rect = item.trigger.getBoundingClientRect();
  const bounds = getViewportBounds(item.trigger);
  const availableWidth = Math.max(120, bounds.maxRight - bounds.minLeft);
  tip.style.maxWidth = `${Math.min(280, availableWidth)}px`;
  return placeTooltip(
    rect,
    { width: tip.offsetWidth, height: tip.offsetHeight },
    bounds,
    item,
  );
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
  disabled?: boolean;
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
  disabled = false,
  className = "",
  children,
}: TooltipProps) {
  const context = useContext(TooltipContext);
  const triggerRef = useRef<HTMLSpanElement | null>(null);
  const tooltipId = useId();
  const isOpen = context?.activeId === tooltipId;

  const triggerShow = useCallback((immediate = false) => {
    if (disabled || !context || !triggerRef.current) return;
    context.show({
      id: tooltipId,
      content,
      trigger: triggerRef.current,
      side,
      sideOffset,
      align,
      alignOffset,
    }, immediate);
  }, [align, alignOffset, content, context, disabled, side, sideOffset, tooltipId]);

  useEffect(() => {
    if (disabled) {
      if (isOpen) context?.hide(tooltipId, true);
      return;
    }
    if (isOpen) context?.updateContent(tooltipId, content);
  }, [content, context, disabled, isOpen, tooltipId]);

  return (
    <span
      ref={triggerRef}
      className={["ui-tooltip-trigger", className].filter(Boolean).join(" ")}
      aria-describedby={isOpen ? tooltipId : undefined}
      onPointerEnter={(event) => {
        if (disabled || event.pointerType === "touch") return;
        triggerShow(false);
      }}
      onPointerLeave={() => context?.hide(tooltipId, false)}
      onPointerDown={() => context?.hide(tooltipId, true)}
      onFocus={(event) => {
        if (!disabled && event.target instanceof Element && event.target.matches(":focus-visible")) {
          triggerShow(true);
        }
      }}
      onBlur={() => context?.hide(tooltipId, true)}
    >
      {children}
    </span>
  );
}

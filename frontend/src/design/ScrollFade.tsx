import {
    useCallback,
    useEffect,
    useLayoutEffect,
    useRef,
    type CSSProperties,
    type ReactNode,
} from "react";
import { computeScrollTargetForItem } from "./scrollFadeMath";

type ScrollFadeProps = {
    size?: number;
    shrink?: number;
    blur?: number;
    className?: string;
    role?: string;
    ariaLabel?: string;
    children: ReactNode;
};

/** Horizontal scroll container with progressive edge blur, smooth mask fade, and auto-centering for edge-blurred items. */
export function ScrollFade({
    size = 56,
    shrink = 0.03,
    blur = 4,
    className = "",
    role,
    ariaLabel,
    children,
}: ScrollFadeProps) {
    const viewportRef = useRef<HTMLDivElement | null>(null);
    const trackRef = useRef<HTMLDivElement | null>(null);
    const leftEdgeRef = useRef<HTMLDivElement | null>(null);
    const rightEdgeRef = useRef<HTMLDivElement | null>(null);
    const scrollRafRef = useRef<number>(0);

    const syncFade = useCallback(() => {
        const viewport = viewportRef.current;
        const track = trackRef.current;
        const leftEdge = leftEdgeRef.current;
        const rightEdge = rightEdgeRef.current;
        if (!viewport || !track) return;

        const clientWidth = viewport.clientWidth;
        const scrollWidth = viewport.scrollWidth;
        const scrollLeft = viewport.scrollLeft;
        const maxScroll = Math.max(0, scrollWidth - clientWidth);

        const leftRamp =
            maxScroll > 1 ? Math.min(1, Math.max(0, scrollLeft / 24)) : 0;
        const rightRamp =
            maxScroll > 1
                ? Math.min(1, Math.max(0, (maxScroll - scrollLeft) / 24))
                : 0;

        const leftFade = maxScroll > 1 && scrollLeft > 0.5 ? size * leftRamp : 0;
        const rightFade =
            maxScroll > 1 && maxScroll - scrollLeft > 0.5
                ? size * rightRamp
                : 0;

        if (leftFade > 0.5 || rightFade > 0.5) {
            const leftStop =
                leftFade > 0.5
                    ? [
                          `rgb(0 0 0 / 0.06) 0px`,
                          `rgb(0 0 0 / 0.24) ${(leftFade * 0.24).toFixed(1)}px`,
                          `rgb(0 0 0 / 0.58) ${(leftFade * 0.52).toFixed(1)}px`,
                          `rgb(0 0 0 / 0.88) ${(leftFade * 0.78).toFixed(1)}px`,
                          `#000 ${leftFade.toFixed(1)}px`,
                      ].join(", ")
                    : "#000 0px";
            const rightStop =
                rightFade > 0.5
                    ? [
                          `#000 calc(100% - ${rightFade.toFixed(1)}px)`,
                          `rgb(0 0 0 / 0.88) calc(100% - ${(rightFade * 0.78).toFixed(1)}px)`,
                          `rgb(0 0 0 / 0.58) calc(100% - ${(rightFade * 0.52).toFixed(1)}px)`,
                          `rgb(0 0 0 / 0.24) calc(100% - ${(rightFade * 0.24).toFixed(1)}px)`,
                          `rgb(0 0 0 / 0.06) 100%`,
                      ].join(", ")
                    : "#000 100%";
            const mask = `linear-gradient(to right, ${leftStop}, ${rightStop})`;
            viewport.style.maskImage = mask;
            viewport.style.webkitMaskImage = mask;
        } else {
            viewport.style.maskImage = "";
            viewport.style.webkitMaskImage = "";
        }

        const reducedMotion =
            window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ??
            false;

        if (leftEdge) {
            leftEdge.style.opacity = reducedMotion ? "0" : leftRamp.toFixed(3);
        }
        if (rightEdge) {
            rightEdge.style.opacity = reducedMotion
                ? "0"
                : rightRamp.toFixed(3);
        }

        const items = Array.from(track.children) as HTMLElement[];
        for (const item of items) {
            if (item.style.filter) item.style.filter = "";
            if (
                reducedMotion ||
                shrink <= 0 ||
                (leftFade <= 0.5 && rightFade <= 0.5)
            ) {
                if (item.style.transform) item.style.transform = "";
                continue;
            }
            const itemCenter = item.offsetLeft - scrollLeft + item.offsetWidth / 2;
            let progress = 0;
            if (leftFade > 0.5 && itemCenter < leftFade) {
                progress = Math.min(
                    1,
                    Math.max(0, (leftFade - itemCenter) / Math.max(1, leftFade)),
                );
            } else if (
                rightFade > 0.5 &&
                itemCenter > clientWidth - rightFade
            ) {
                progress = Math.min(
                    1,
                    Math.max(
                        0,
                        (itemCenter - (clientWidth - rightFade)) /
                            Math.max(1, rightFade),
                    ),
                );
            }
            if (progress <= 0.005) {
                if (item.style.transform) item.style.transform = "";
            } else {
                const scale = 1 - shrink * progress;
                item.style.transform = `scale(${scale.toFixed(4)})`;
            }
        }
    }, [shrink, size]);

    const scrollItemIntoSharpView = useCallback(
        (targetElement: EventTarget | null) => {
            if (!(targetElement instanceof Node)) return;
            if (scrollRafRef.current !== 0) {
                window.cancelAnimationFrame(scrollRafRef.current);
            }
            scrollRafRef.current = window.requestAnimationFrame(() => {
                scrollRafRef.current = 0;
                const viewport = viewportRef.current;
                const track = trackRef.current;
                if (!viewport || !track) return;

                const items = Array.from(track.children) as HTMLElement[];
                const index = items.findIndex((item) =>
                    item.contains(targetElement),
                );
                if (index < 0) return;

                const targetScroll = computeScrollTargetForItem(
                    items.map((el) => ({
                        left: el.offsetLeft,
                        width: el.offsetWidth,
                    })),
                    index,
                    {
                        clientWidth: viewport.clientWidth,
                        scrollWidth: viewport.scrollWidth,
                        scrollLeft: viewport.scrollLeft,
                        fadeSize: size,
                    },
                );
                if (targetScroll === null) return;

                const reducedMotion =
                    window.matchMedia?.("(prefers-reduced-motion: reduce)")
                        .matches ?? false;
                viewport.scrollTo({
                    left: targetScroll,
                    behavior: reducedMotion ? "auto" : "smooth",
                });
            });
        },
        [size],
    );

    useEffect(
        () => () => {
            if (scrollRafRef.current !== 0) {
                window.cancelAnimationFrame(scrollRafRef.current);
            }
        },
        [],
    );

    useLayoutEffect(() => {
        syncFade();
    });

    useEffect(() => {
        const viewport = viewportRef.current;
        const track = trackRef.current;
        if (!viewport || !track) return;

        syncFade();
        const onScroll = () => syncFade();
        viewport.addEventListener("scroll", onScroll, { passive: true });
        window.addEventListener("resize", syncFade);

        const resizeObserver =
            typeof ResizeObserver !== "undefined"
                ? new ResizeObserver(syncFade)
                : null;
        resizeObserver?.observe(viewport);
        resizeObserver?.observe(track);

        return () => {
            viewport.removeEventListener("scroll", onScroll);
            window.removeEventListener("resize", syncFade);
            resizeObserver?.disconnect();
        };
    }, [syncFade]);

    const rootStyle = {
        "--scroll-fade-size": `${size}px`,
        "--scroll-fade-blur-soft": `${(blur * 0.3).toFixed(2)}px`,
        "--scroll-fade-blur-mid": `${(blur * 0.65).toFixed(2)}px`,
        "--scroll-fade-blur-strong": `${blur.toFixed(2)}px`,
    } as CSSProperties;

    return (
        <div
            className={["ui-scroll-fade-root", className]
                .filter(Boolean)
                .join(" ")}
            style={rootStyle}
        >
            <div
                ref={viewportRef}
                className="ui-scroll-fade"
                role={role}
                aria-label={ariaLabel}
                onClick={(event) => {
                    if (
                        event.target instanceof Element &&
                        event.target.closest("button:not(:disabled)")
                    ) {
                        scrollItemIntoSharpView(event.target);
                    }
                }}
                onFocus={(event) => {
                    if (
                        event.target instanceof Element &&
                        event.target.matches(":focus-visible")
                    ) {
                        scrollItemIntoSharpView(event.target);
                    }
                }}
                onWheel={(event) => {
                    if (event.ctrlKey) return;
                    const el = event.currentTarget;
                    if (el.scrollWidth <= el.clientWidth + 1) return;
                    if (Math.abs(event.deltaY) > Math.abs(event.deltaX)) {
                        el.scrollLeft += event.deltaY;
                        event.stopPropagation();
                    }
                }}
            >
                <div ref={trackRef} className="ui-scroll-fade-track">
                    {children}
                </div>
            </div>
            <div
                ref={leftEdgeRef}
                className="ui-scroll-fade-edge is-left"
                aria-hidden="true"
            >
                <span className="ui-scroll-fade-blur is-soft" />
                <span className="ui-scroll-fade-blur is-mid" />
                <span className="ui-scroll-fade-blur is-strong" />
            </div>
            <div
                ref={rightEdgeRef}
                className="ui-scroll-fade-edge is-right"
                aria-hidden="true"
            >
                <span className="ui-scroll-fade-blur is-soft" />
                <span className="ui-scroll-fade-blur is-mid" />
                <span className="ui-scroll-fade-blur is-strong" />
            </div>
        </div>
    );
}

import {
    useCallback,
    useEffect,
    useLayoutEffect,
    useRef,
    useState,
    type RefObject,
} from "react";
import { computeScrollbarMetrics } from "./scrollbarMath";

type ScrollbarProps = {
    targetRef: RefObject<HTMLElement | null>;
    orientation: "horizontal" | "vertical";
    ariaLabel: string;
    className?: string;
};

/** Custom Figma-styled scrollbar rail that remains visible at full span even before overflow occurs. */
export function Scrollbar({
    targetRef,
    orientation,
    ariaLabel,
    className = "",
}: ScrollbarProps) {
    const trackRef = useRef<HTMLDivElement | null>(null);
    const thumbRef = useRef<HTMLDivElement | null>(null);
    const metricsRef = useRef({
        scrollable: false,
        maxScroll: 0,
        maxOffset: 0,
        thumbSize: 0,
    });
    const dragRef = useRef<{
        pointerId: number;
        startClient: number;
        startScroll: number;
    } | null>(null);
    const [scrollable, setScrollable] = useState(false);
    const [dragging, setDragging] = useState(false);
    const isHorizontal = orientation === "horizontal";

    const sync = useCallback(() => {
        const target = targetRef.current;
        const track = trackRef.current;
        const thumb = thumbRef.current;
        if (!target || !track || !thumb) return;

        const clientSize = isHorizontal
            ? target.clientWidth
            : target.clientHeight;
        const scrollSize = isHorizontal
            ? target.scrollWidth
            : target.scrollHeight;
        const scrollPos = isHorizontal ? target.scrollLeft : target.scrollTop;
        const trackSize = isHorizontal ? track.clientWidth : track.clientHeight;
        const metrics = computeScrollbarMetrics(
            clientSize,
            scrollSize,
            scrollPos,
            trackSize,
        );

        metricsRef.current = {
            scrollable: metrics.scrollable,
            maxScroll: metrics.maxScroll,
            maxOffset: metrics.maxOffset,
            thumbSize: metrics.thumbSize,
        };
        setScrollable((current) =>
            current === metrics.scrollable ? current : metrics.scrollable,
        );

        if (isHorizontal) {
            thumb.style.width = metrics.scrollable
                ? `${metrics.thumbSize}px`
                : "100%";
            thumb.style.height = "100%";
            thumb.style.transform = `translate3d(${metrics.thumbOffset.toFixed(2)}px, 0, 0)`;
        } else {
            thumb.style.height = metrics.scrollable
                ? `${metrics.thumbSize}px`
                : "100%";
            thumb.style.width = "100%";
            thumb.style.transform = `translate3d(0, ${metrics.thumbOffset.toFixed(2)}px, 0)`;
        }
    }, [isHorizontal, targetRef]);

    useLayoutEffect(() => {
        sync();
    });

    useEffect(() => {
        const target = targetRef.current;
        const track = trackRef.current;
        if (!target || !track) return;

        sync();
        const onScroll = () => sync();
        target.addEventListener("scroll", onScroll, { passive: true });
        window.addEventListener("resize", sync);

        const resizeObserver =
            typeof ResizeObserver !== "undefined"
                ? new ResizeObserver(sync)
                : null;
        resizeObserver?.observe(target);
        resizeObserver?.observe(track);

        const mutationObserver =
            typeof MutationObserver !== "undefined"
                ? new MutationObserver(sync)
                : null;
        mutationObserver?.observe(target, {
            childList: true,
            subtree: true,
            attributes: true,
        });

        return () => {
            target.removeEventListener("scroll", onScroll);
            window.removeEventListener("resize", sync);
            resizeObserver?.disconnect();
            mutationObserver?.disconnect();
        };
    }, [sync, targetRef]);

    function scrollByThumbOffset(nextOffset: number) {
        const target = targetRef.current;
        const {
            scrollable: canScroll,
            maxScroll,
            maxOffset,
        } = metricsRef.current;
        if (!target || !canScroll || maxOffset <= 0) return;
        const clamped = Math.min(maxOffset, Math.max(0, nextOffset));
        const scrollPos = (clamped / maxOffset) * maxScroll;
        if (isHorizontal) target.scrollLeft = scrollPos;
        else target.scrollTop = scrollPos;
    }

    return (
        <div
            ref={trackRef}
            role="scrollbar"
            aria-label={ariaLabel}
            aria-orientation={orientation}
            aria-disabled={!scrollable}
            data-scrollable={scrollable ? "true" : "false"}
            className={[
                "ui-scrollbar",
                `ui-scrollbar--${orientation}`,
                scrollable ? "is-scrollable" : "is-disabled",
                dragging ? "is-dragging" : "",
                className,
            ]
                .filter(Boolean)
                .join(" ")}
            onPointerDown={(event) => {
                if (!scrollable) return;
                if (event.target === thumbRef.current) return;
                const track = trackRef.current;
                if (!track) return;
                const rect = track.getBoundingClientRect();
                const pointerPos = isHorizontal
                    ? event.clientX - rect.left
                    : event.clientY - rect.top;
                scrollByThumbOffset(
                    pointerPos - metricsRef.current.thumbSize / 2,
                );
            }}
        >
            <div
                ref={thumbRef}
                className="ui-scrollbar-thumb"
                onPointerDown={(event) => {
                    const target = targetRef.current;
                    if (!scrollable || !target || event.button !== 0) return;
                    event.preventDefault();
                    event.stopPropagation();
                    event.currentTarget.setPointerCapture(event.pointerId);
                    dragRef.current = {
                        pointerId: event.pointerId,
                        startClient: isHorizontal
                            ? event.clientX
                            : event.clientY,
                        startScroll: isHorizontal
                            ? target.scrollLeft
                            : target.scrollTop,
                    };
                    setDragging(true);
                }}
                onPointerMove={(event) => {
                    const drag = dragRef.current;
                    const target = targetRef.current;
                    const {
                        scrollable: canScroll,
                        maxScroll,
                        maxOffset,
                    } = metricsRef.current;
                    if (
                        !drag ||
                        !target ||
                        !canScroll ||
                        maxOffset <= 0 ||
                        event.pointerId !== drag.pointerId
                    )
                        return;
                    const delta =
                        (isHorizontal ? event.clientX : event.clientY) -
                        drag.startClient;
                    const nextScroll =
                        drag.startScroll + (delta / maxOffset) * maxScroll;
                    if (isHorizontal) target.scrollLeft = nextScroll;
                    else target.scrollTop = nextScroll;
                }}
                onPointerUp={(event) => {
                    if (dragRef.current?.pointerId === event.pointerId) {
                        dragRef.current = null;
                        setDragging(false);
                    }
                }}
                onPointerCancel={(event) => {
                    if (dragRef.current?.pointerId === event.pointerId) {
                        dragRef.current = null;
                        setDragging(false);
                    }
                }}
            />
        </div>
    );
}

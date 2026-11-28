import { useId, useLayoutEffect, useRef } from "react";

type Option<T extends string> = { value: T; label: string; disabled?: boolean };

type Props<T extends string> = {
    label: string;
    value: T;
    options: readonly Option<T>[];
    onChange: (value: T) => void;
    disabled?: boolean;
};

type Rect = { left: number; top: number; width: number; height: number };

// Animate UI Highlight spring (stiffness: 350, damping: 35, mass: 1).
const HIGHLIGHT_SPRING =
    "linear(0.000, 0.037 5%, 0.124 10%, 0.233 15%, 0.348 20%, 0.458 25%, 0.557 30%, 0.645 35%, 0.718 40%, 0.780 45%, 0.830 50%, 0.870 55%, 0.902 60%, 0.927 65%, 0.946 70%, 0.961 75%, 0.972 80%, 0.980 85%, 0.986 90%, 0.990 95%, 1.000)";

/** A native radio group styled as the UI Kit segment control with a Highlight-style gliding indicator. */
export function SegmentedControl<T extends string>({
    label,
    value,
    options,
    onChange,
    disabled,
}: Props<T>) {
    const name = useId();
    const groupRef = useRef<HTMLDivElement>(null);
    const indicatorRef = useRef<HTMLSpanElement>(null);
    const optionRefs = useRef(new Map<T, HTMLLabelElement>());
    const lastValue = useRef<T | null>(null);
    const lastRect = useRef<Rect | null>(null);
    const activeAnimation = useRef<Animation | null>(null);

    useLayoutEffect(() => {
        const group = groupRef.current;
        const indicator = indicatorRef.current;
        const target = optionRefs.current.get(value);
        if (!group || !indicator || !target) {
            if (indicator) indicator.style.opacity = "0";
            lastValue.current = null;
            lastRect.current = null;
            return;
        }

        const measure = (): Rect => ({
            left: target.offsetLeft,
            top: target.offsetTop,
            width: target.offsetWidth,
            height: target.offsetHeight,
        });

        const applyRect = (rect: Rect) => {
            indicator.style.transform = `translate3d(${rect.left}px, ${rect.top}px, 0)`;
            indicator.style.width = `${rect.width}px`;
            indicator.style.height = `${rect.height}px`;
            indicator.style.opacity = "1";
        };

        const nextRect = measure();
        const shouldAnimate =
            lastValue.current !== null &&
            lastValue.current !== value &&
            lastRect.current !== null &&
            typeof indicator.animate === "function" &&
            !window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

        if (shouldAnimate) {
            let fromRect = lastRect.current!;
            if (activeAnimation.current) {
                const computed = window.getComputedStyle(indicator);
                const matrix = new DOMMatrixReadOnly(
                    computed.transform === "none"
                        ? undefined
                        : computed.transform,
                );
                fromRect = {
                    left: matrix.m41,
                    top: matrix.m42,
                    width: parseFloat(computed.width) || fromRect.width,
                    height: parseFloat(computed.height) || fromRect.height,
                };
                activeAnimation.current.cancel();
            }
            applyRect(nextRect);
            const animation = indicator.animate(
                [
                    {
                        transform: `translate3d(${fromRect.left}px, ${fromRect.top}px, 0)`,
                        width: `${fromRect.width}px`,
                        height: `${fromRect.height}px`,
                    },
                    {
                        transform: `translate3d(${nextRect.left}px, ${nextRect.top}px, 0)`,
                        width: `${nextRect.width}px`,
                        height: `${nextRect.height}px`,
                    },
                ],
                { duration: 320, easing: HIGHLIGHT_SPRING },
            );
            activeAnimation.current = animation;
            void animation.finished
                .then(() => {
                    if (activeAnimation.current === animation)
                        activeAnimation.current = null;
                })
                .catch(() => undefined);
        } else {
            activeAnimation.current?.cancel();
            activeAnimation.current = null;
            applyRect(nextRect);
        }

        lastValue.current = value;
        lastRect.current = nextRect;

        if (typeof ResizeObserver === "undefined") return undefined;
        const observer = new ResizeObserver(() => {
            const updated = measure();
            if (updated.width <= 0 || updated.height <= 0) return;
            if (
                lastRect.current &&
                lastRect.current.left === updated.left &&
                lastRect.current.top === updated.top &&
                lastRect.current.width === updated.width &&
                lastRect.current.height === updated.height
            ) {
                return;
            }
            activeAnimation.current?.cancel();
            activeAnimation.current = null;
            applyRect(updated);
            lastRect.current = updated;
        });
        observer.observe(group);
        observer.observe(target);
        return () => observer.disconnect();
    }, [value, options]);

    const activeOption = options.find((option) => option.value === value);
    const selectedDisabled = Boolean(disabled || activeOption?.disabled);
    const allDisabled = Boolean(
        disabled ||
        (options.length > 0 && options.every((option) => option.disabled)),
    );

    return (
        <div
            className={`ui-segmented${allDisabled ? " is-disabled" : ""}${selectedDisabled ? " is-selected-disabled" : ""}`}
            role="radiogroup"
            aria-label={label}
            aria-disabled={allDisabled || undefined}
            ref={groupRef}
        >
            <span
                className="ui-segmented-indicator"
                ref={indicatorRef}
                aria-hidden="true"
            />
            {options.map((option) => {
                const active = value === option.value;
                const optionDisabled = Boolean(disabled || option.disabled);
                return (
                    <label
                        className="ui-segmented-option"
                        data-active={active ? "true" : "false"}
                        data-disabled={optionDisabled ? "true" : "false"}
                        data-value={option.value}
                        key={option.value}
                        ref={(node) => {
                            if (node)
                                optionRefs.current.set(option.value, node);
                            else optionRefs.current.delete(option.value);
                        }}
                    >
                        <input
                            type="radio"
                            name={name}
                            value={option.value}
                            checked={active}
                            disabled={optionDisabled}
                            onChange={() => onChange(option.value)}
                        />
                        <span>{option.label}</span>
                    </label>
                );
            })}
        </div>
    );
}

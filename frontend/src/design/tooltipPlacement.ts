export type TooltipSide = "top" | "bottom";
export type TooltipAlign = "start" | "center" | "end";

export type TooltipRect = {
    left: number;
    top: number;
    right: number;
    bottom: number;
    width: number;
    height: number;
};

export type TooltipBounds = {
    minLeft: number;
    maxRight: number;
    minTop: number;
    maxBottom: number;
};

export type ViewportInsetBox = {
    rect: Pick<TooltipRect, "left" | "top" | "right" | "bottom">;
    rightInset: number;
    bottomInset: number;
};

/** Computes horizontal and vertical clamping bounds for a tooltip inside the window or viewport. */
export function computeTooltipBounds(
    windowWidth: number,
    windowHeight: number,
    viewport: ViewportInsetBox | null,
): TooltipBounds {
    if (!viewport) {
        return {
            minLeft: 8,
            maxRight: Math.max(8, windowWidth - 8),
            minTop: 8,
            maxBottom: Math.max(8, windowHeight - 8),
        };
    }
    const padding = 16;
    const minLeft = Math.max(8, viewport.rect.left + padding);
    const maxRight = Math.min(
        windowWidth - 8,
        viewport.rect.right - viewport.rightInset - padding,
    );
    const minTop = Math.max(8, viewport.rect.top + padding);
    const maxBottom = Math.min(
        windowHeight - 8,
        viewport.rect.bottom - viewport.bottomInset - padding,
    );
    return {
        minLeft,
        maxRight: Math.max(minLeft, maxRight),
        minTop,
        maxBottom: Math.max(minTop, maxBottom),
    };
}

/** Positions a measured tooltip within its bounds while keeping transform origin anchored to the trigger. */
export function placeTooltip(
    trigger: TooltipRect,
    tipSize: { width: number; height: number },
    bounds: TooltipBounds,
    options: {
        side: TooltipSide;
        sideOffset: number;
        align: TooltipAlign;
        alignOffset: number;
    },
) {
    let top =
        options.side === "bottom"
            ? trigger.bottom + options.sideOffset
            : trigger.top - options.sideOffset - tipSize.height;
    let resolvedSide = options.side;
    if (options.side === "bottom" && top + tipSize.height > bounds.maxBottom) {
        const above = trigger.top - options.sideOffset - tipSize.height;
        if (above >= bounds.minTop) {
            top = above;
            resolvedSide = "top";
        }
    } else if (options.side === "top" && top < bounds.minTop) {
        const below = trigger.bottom + options.sideOffset;
        if (below + tipSize.height <= bounds.maxBottom) {
            top = below;
            resolvedSide = "bottom";
        }
    }
    top = Math.max(
        bounds.minTop,
        Math.min(
            top,
            Math.max(bounds.minTop, bounds.maxBottom - tipSize.height),
        ),
    );

    let rawLeft = trigger.left + trigger.width / 2 - tipSize.width / 2;
    if (options.align === "start") rawLeft = trigger.left;
    else if (options.align === "end") rawLeft = trigger.right - tipSize.width;
    rawLeft += options.alignOffset;
    const left = Math.max(
        bounds.minLeft,
        Math.min(
            rawLeft,
            Math.max(bounds.minLeft, bounds.maxRight - tipSize.width),
        ),
    );

    const triggerCenter = trigger.left + trigger.width / 2;
    const originX = Math.max(
        8,
        Math.min(tipSize.width - 8, triggerCenter - left),
    );
    const originY = resolvedSide === "bottom" ? 0 : tipSize.height;

    return {
        top,
        left,
        width: tipSize.width,
        height: tipSize.height,
        side: resolvedSide,
        transformOrigin: `${originX.toFixed(1)}px ${originY.toFixed(1)}px`,
    };
}

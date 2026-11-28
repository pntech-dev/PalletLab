export type ScrollFadeItemBox = {
    left: number;
    width: number;
};

export type ScrollFadeViewportMetrics = {
    clientWidth: number;
    scrollWidth: number;
    scrollLeft: number;
    fadeSize: number;
};

const SCROLL_EPSILON = 1;

function clamp(value: number, min: number, max: number): number {
    return Math.min(max, Math.max(min, value));
}

export function activeFadeZones(
    scrollLeft: number,
    maxScroll: number,
    fadeSize: number,
): { leftZone: number; rightZone: number } {
    if (maxScroll <= SCROLL_EPSILON) return { leftZone: 0, rightZone: 0 };
    const clamped = clamp(scrollLeft, 0, maxScroll);
    return {
        leftZone: clamped > 0.5 ? fadeSize : 0,
        rightZone: maxScroll - clamped > 0.5 ? fadeSize : 0,
    };
}

export function isItemInFadeZone(
    item: ScrollFadeItemBox,
    scrollLeft: number,
    clientWidth: number,
    maxScroll: number,
    fadeSize: number,
): boolean {
    const { leftZone, rightZone } = activeFadeZones(
        scrollLeft,
        maxScroll,
        fadeSize,
    );
    const visLeft = item.left - scrollLeft;
    const visRight = visLeft + item.width;
    return (
        visLeft < leftZone - SCROLL_EPSILON ||
        visRight > clientWidth - rightZone + SCROLL_EPSILON
    );
}

function sharpVisibleWidth(
    item: ScrollFadeItemBox,
    scrollLeft: number,
    clientWidth: number,
    maxScroll: number,
    fadeSize: number,
): number {
    const { leftZone, rightZone } = activeFadeZones(
        scrollLeft,
        maxScroll,
        fadeSize,
    );
    const sharpStart = leftZone;
    const sharpEnd = Math.max(sharpStart, clientWidth - rightZone);
    const visLeft = item.left - scrollLeft;
    const visRight = visLeft + item.width;
    return Math.max(
        0,
        Math.min(visRight, sharpEnd) - Math.max(visLeft, sharpStart),
    );
}

/**
 * Computes the target scrollLeft when clicking an item inside ScrollFade.
 * Returns null if the item is already completely outside any blur/fade zone.
 * Otherwise centers the item when possible while avoiding blurring it or its neighbors.
 */
export function computeScrollTargetForItem(
    items: readonly ScrollFadeItemBox[],
    index: number,
    metrics: ScrollFadeViewportMetrics,
): number | null {
    const item = items[index];
    if (!item) return null;

    const { clientWidth, scrollWidth, scrollLeft, fadeSize } = metrics;
    const maxScroll = Math.max(0, scrollWidth - clientWidth);
    if (maxScroll <= SCROLL_EPSILON) return null;

    if (!isItemInFadeZone(item, scrollLeft, clientWidth, maxScroll, fadeSize)) {
        return null;
    }

    const centered = clamp(
        item.left + item.width / 2 - clientWidth / 2,
        0,
        maxScroll,
    );

    const candidates = new Set<number>([centered, 0, maxScroll]);

    const addSpanClosestToCentered = (spanLeft: number, spanRight: number) => {
        const minS = spanRight - (clientWidth - fadeSize);
        const maxS = spanLeft - fadeSize;
        if (minS <= maxS) {
            candidates.add(clamp(centered, clamp(minS, 0, maxScroll), clamp(maxS, 0, maxScroll)));
        }
    };

    addSpanClosestToCentered(item.left, item.left + item.width);

    const prevItem = index > 0 ? items[index - 1] : undefined;
    const nextItem = index < items.length - 1 ? items[index + 1] : undefined;

    if (prevItem) {
        addSpanClosestToCentered(prevItem.left, item.left + item.width);
    }
    if (nextItem) {
        addSpanClosestToCentered(item.left, nextItem.left + nextItem.width);
    }
    if (prevItem && nextItem) {
        const groupLeft = prevItem.left;
        const groupRight = nextItem.left + nextItem.width;
        candidates.add(
            clamp((groupLeft + groupRight) / 2 - clientWidth / 2, 0, maxScroll),
        );
        addSpanClosestToCentered(groupLeft, groupRight);
    }

    let bestScroll = centered;
    let bestScore: [number, number, number, number] | null = null;

    for (const s of candidates) {
        const selfSharp = isItemInFadeZone(
            item,
            s,
            clientWidth,
            maxScroll,
            fadeSize,
        )
            ? 0
            : 1;
        let neighborsSharp = 0;
        if (
            prevItem &&
            !isItemInFadeZone(prevItem, s, clientWidth, maxScroll, fadeSize)
        ) {
            neighborsSharp += 1;
        }
        if (
            nextItem &&
            !isItemInFadeZone(nextItem, s, clientWidth, maxScroll, fadeSize)
        ) {
            neighborsSharp += 1;
        }
        const sharpPx = sharpVisibleWidth(
            item,
            s,
            clientWidth,
            maxScroll,
            fadeSize,
        );
        const dist = Math.abs(s - centered);
        const score: [number, number, number, number] = [
            selfSharp,
            neighborsSharp,
            sharpPx,
            -dist,
        ];
        if (
            !bestScore ||
            score[0] > bestScore[0] ||
            (score[0] === bestScore[0] && score[1] > bestScore[1]) ||
            (score[0] === bestScore[0] &&
                score[1] === bestScore[1] &&
                score[2] > bestScore[2]) ||
            (score[0] === bestScore[0] &&
                score[1] === bestScore[1] &&
                score[2] === bestScore[2] &&
                score[3] > bestScore[3])
        ) {
            bestScore = score;
            bestScroll = s;
        }
    }

    if (Math.abs(bestScroll - scrollLeft) <= SCROLL_EPSILON) return null;
    return bestScroll;
}

export type Rect = { left: number; top: number; right: number; bottom: number };

/** Place a cursor tip in the nearest available space, keeping clear of overlays. */
export function placeViewportHint(
    pointer: [number, number],
    size: { width: number; height: number },
    bounds: Rect,
    obstacles: Rect[],
    gap = 16,
): [number, number] {
    const maxX = Math.max(bounds.left, bounds.right - size.width);
    const maxY = Math.max(bounds.top, bounds.bottom - size.height);
    const clampX = (x: number) => Math.max(bounds.left, Math.min(maxX, x));
    const clampY = (y: number) => Math.max(bounds.top, Math.min(maxY, y));
    const desiredX = pointer[0] + gap;
    const desiredY = pointer[1] + gap;
    const xs = [
        clampX(desiredX),
        clampX(pointer[0] - gap - size.width),
        bounds.left,
        maxX,
    ];
    const ys = [
        clampY(desiredY),
        clampY(pointer[1] - gap - size.height),
        bounds.top,
        maxY,
    ];
    for (const obstacle of obstacles) {
        xs.push(
            clampX(obstacle.left - gap - size.width),
            clampX(obstacle.right + gap),
        );
        ys.push(
            clampY(obstacle.top - gap - size.height),
            clampY(obstacle.bottom + gap),
        );
    }
    let best: [number, number] = [xs[0], ys[0]];
    let bestOverlap = Infinity;
    let bestDistance = Infinity;
    for (const x of xs)
        for (const y of ys) {
            const overlap = obstacles.reduce(
                (sum, rect) =>
                    sum +
                    Math.max(
                        0,
                        Math.min(x + size.width, rect.right + gap) -
                            Math.max(x, rect.left - gap),
                    ) *
                        Math.max(
                            0,
                            Math.min(y + size.height, rect.bottom + gap) -
                                Math.max(y, rect.top - gap),
                        ),
                0,
            );
            const distance = (x - desiredX) ** 2 + (y - desiredY) ** 2;
            if (
                overlap < bestOverlap ||
                (overlap === bestOverlap && distance < bestDistance)
            ) {
                best = [x, y];
                bestOverlap = overlap;
                bestDistance = distance;
            }
        }
    return best;
}

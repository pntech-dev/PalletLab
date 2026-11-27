import { strict as assert } from "node:assert";
import { test } from "node:test";
import { computeTooltipBounds, placeTooltip } from "../src/design/tooltipPlacement.ts";

test("clamps viewport tooltips inside the visible clipped viewport with 16px margins", () => {
  const bounds = computeTooltipBounds(1440, 900, {
    rect: { left: 8, top: 60, right: 1432, bottom: 892 },
    rightInset: 508,
    bottomInset: 180,
  });
  assert.deepEqual(bounds, {
    minLeft: 24,
    maxRight: 908,
    minTop: 76,
    maxBottom: 696,
  });

  // Fullscreen toggle button anchored at top-right of the visible viewport (right = 908).
  const fullscreenButton = { left: 872, top: 76, right: 908, bottom: 112, width: 36, height: 36 };
  const placed = placeTooltip(
    fullscreenButton,
    { width: 260, height: 48 },
    bounds,
    { side: "bottom", sideOffset: 6, align: "center", alignOffset: 0 },
  );
  assert.equal(placed.left + placed.width, 908);
  assert.equal(placed.top, 118);
  assert.equal(placed.side, "bottom");
});

test("keeps bottom-right zoom and top-left toolbar tooltips within viewport padding", () => {
  const bounds = computeTooltipBounds(1440, 900, {
    rect: { left: 8, top: 60, right: 1432, bottom: 892 },
    rightInset: 0,
    bottomInset: 0,
  });
  assert.deepEqual(bounds, {
    minLeft: 24,
    maxRight: 1416,
    minTop: 76,
    maxBottom: 876,
  });

  const leftButton = { left: 24, top: 76, right: 60, bottom: 112, width: 36, height: 36 };
  const leftTip = placeTooltip(
    leftButton,
    { width: 200, height: 32 },
    bounds,
    { side: "bottom", sideOffset: 6, align: "center", alignOffset: 0 },
  );
  assert.equal(leftTip.left, 24);

  const zoomPlus = { left: 1380, top: 840, right: 1416, bottom: 876, width: 36, height: 36 };
  const zoomTip = placeTooltip(
    zoomPlus,
    { width: 240, height: 32 },
    bounds,
    { side: "top", sideOffset: 6, align: "center", alignOffset: 0 },
  );
  assert.equal(zoomTip.left + zoomTip.width, 1416);
  assert.equal(zoomTip.top + zoomTip.height, 834);
  assert.equal(zoomTip.side, "top");
});

test("keeps non-viewport tooltips within an 8px window margin", () => {
  const bounds = computeTooltipBounds(1280, 720, null);
  assert.deepEqual(bounds, {
    minLeft: 8,
    maxRight: 1272,
    minTop: 8,
    maxBottom: 712,
  });
});

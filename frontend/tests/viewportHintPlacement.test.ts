import { strict as assert } from "node:assert";
import { test } from "node:test";
import { placeViewportHint, type Rect } from "../src/viewportHintPlacement.ts";

const bounds = { left: 16, top: 68, right: 984, bottom: 700 };
const size = { width: 300, height: 80 };
const overlaps = ([x, y]: [number, number], rect: Rect) =>
  x < rect.right + 16 && x + size.width > rect.left - 16 && y < rect.bottom + 16 && y + size.height > rect.top - 16;

test("keeps the measured tip within the viewport's reserved edges", () => {
  for (const pointer of [[-20, -20], [1200, -20], [-20, 900], [1200, 900]] as [number, number][]) {
    const [x, y] = placeViewportHint(pointer, size, bounds, []);
    assert.ok(x >= bounds.left && x + size.width <= bounds.right);
    assert.ok(y >= bounds.top && y + size.height <= bounds.bottom);
  }
});

test("uses one bottom boundary across the full viewport width", () => {
  for (const x of [-100, 100, 500, 900, 1200]) {
    const [, y] = placeViewportHint([x, 1000], size, bounds, []);
    assert.equal(y + size.height, bounds.bottom);
  }
});

test("moves the tip outside HUDs and other overlays with a 16px gap", () => {
  const overlays = [{ left: 330, top: 250, right: 586, bottom: 524 }, { left: 640, top: 200, right: 800, bottom: 300 }];
  for (const pointer of [[400, 300], [330, 250], [570, 510]] as [number, number][]) {
    const position = placeViewportHint(pointer, size, bounds, overlays);
    assert.ok(overlays.every(rect => !overlaps(position, rect)));
    assert.ok(position[0] >= bounds.left && position[0] + size.width <= bounds.right);
    assert.ok(position[1] >= bounds.top && position[1] + size.height <= bounds.bottom);
  }
});

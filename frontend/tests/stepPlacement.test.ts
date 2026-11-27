import assert from "node:assert/strict";
import test from "node:test";
import { stepViewportTransform } from "../src/stepPlacement.ts";

test("STEP model follows the highest beam without accumulating movement", () => {
  const transform = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 2, .21, 3, 1];
  const placement = { transform, starts: [100, 200] as [number, number], bearingHeight: 210 };
  assert.deepEqual(stepViewportTransform(placement, [150, 0, 240, 0], 310).slice(12, 15), [2.05, .31, 3.04]);
  const lowered = stepViewportTransform(placement, [100, 0, 200, 0], 160);
  assert.ok(Math.abs(lowered[13] - .16) < 1e-9);
  assert.deepEqual(placement.transform, transform);
});

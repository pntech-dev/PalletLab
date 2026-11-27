import { strict as assert } from "node:assert";
import { test } from "node:test";
import { computeScrollbarMetrics } from "../src/design/scrollbarMath.ts";

test("stretches full-size disabled thumb when content does not overflow", () => {
  const fit = computeScrollbarMetrics(400, 400, 0, 400);
  assert.equal(fit.scrollable, false);
  assert.equal(fit.thumbSize, 400);
  assert.equal(fit.thumbOffset, 0);
  assert.equal(fit.maxScroll, 0);
});

test("calculates proportional thumb size and offset when scrolling is needed", () => {
  const overflow = computeScrollbarMetrics(400, 800, 200, 400);
  assert.equal(overflow.scrollable, true);
  assert.equal(overflow.thumbSize, 200);
  assert.equal(overflow.maxScroll, 400);
  assert.equal(overflow.maxOffset, 200);
  assert.equal(overflow.thumbOffset, 100);
});

test("enforces minimum thumb size for long lists", () => {
  const longList = computeScrollbarMetrics(300, 6000, 5700, 300, 32);
  assert.equal(longList.scrollable, true);
  assert.equal(longList.thumbSize, 32);
  assert.equal(longList.thumbOffset, 268);
});

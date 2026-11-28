import { strict as assert } from "node:assert";
import { test } from "node:test";
import {
  computeScrollTargetForItem,
  isItemInFadeZone,
} from "../src/design/scrollFadeMath.ts";

const items = [
  { left: 0, width: 110 },
  { left: 110, width: 100 },
  { left: 210, width: 130 },
  { left: 340, width: 130 },
  { left: 470, width: 150 },
  { left: 620, width: 160 },
  { left: 780, width: 170 },
];
const scrollWidth = 950;
const fadeSize = 56;

test("does not scroll when clicked item is already completely sharp", () => {
  // At scrollLeft = 0, items[0] (0..110) and items[1] (110..210) are inside [0, 480 - 56 = 424].
  assert.equal(
    computeScrollTargetForItem(items, 0, {
      clientWidth: 480,
      scrollWidth,
      scrollLeft: 0,
      fadeSize,
    }),
    null,
  );
  assert.equal(
    computeScrollTargetForItem(items, 1, {
      clientWidth: 480,
      scrollWidth,
      scrollLeft: 0,
      fadeSize,
    }),
    null,
  );
});

test("centers a middle blurred item and keeps neighbors sharp when width allows", () => {
  // At scrollLeft = 0, clientWidth = 480: items[3] (340..470) touches right fade (470 > 424).
  const target = computeScrollTargetForItem(items, 3, {
    clientWidth: 480,
    scrollWidth,
    scrollLeft: 0,
    fadeSize,
  });
  assert.notEqual(target, null);
  const s = target!;
  const maxScroll = scrollWidth - 480;
  assert.equal(isItemInFadeZone(items[3], s, 480, maxScroll, fadeSize), false);
  // Centered is 340 + 65 - 240 = 165. At 165, sharp window is [221, 589].
  // items[2] is 210..340 (touches 221 by 11px), items[4] is 470..620 (touches 589 by 31px).
  // Shifting to 154 keeps items[2] (210 >= 154+56=210) AND items[3] completely sharp!
  assert.equal(isItemInFadeZone(items[2], s, 480, maxScroll, fadeSize), false);
});

test("snaps last item to maxScroll so right edge fade disappears and neighbor stays sharp", () => {
  const clientWidth = 480;
  const maxScroll = scrollWidth - clientWidth;
  const target = computeScrollTargetForItem(items, items.length - 1, {
    clientWidth,
    scrollWidth,
    scrollLeft: 0,
    fadeSize,
  });
  assert.equal(target, maxScroll);
  assert.equal(
    isItemInFadeZone(items[items.length - 1], target!, clientWidth, maxScroll, fadeSize),
    false,
  );
  assert.equal(
    isItemInFadeZone(items[items.length - 2], target!, clientWidth, maxScroll, fadeSize),
    false,
  );
});

test("snaps penultimate item to maxScroll when that keeps both penultimate and last items unblurred", () => {
  const clientWidth = 480;
  const maxScroll = scrollWidth - clientWidth; // 470
  const target = computeScrollTargetForItem(items, items.length - 2, {
    clientWidth,
    scrollWidth,
    scrollLeft: 0,
    fadeSize,
  });
  assert.equal(target, maxScroll);
  assert.equal(
    isItemInFadeZone(items[items.length - 2], target!, clientWidth, maxScroll, fadeSize),
    false,
  );
  assert.equal(
    isItemInFadeZone(items[items.length - 1], target!, clientWidth, maxScroll, fadeSize),
    false,
  );
});

test("snaps first item back to 0 when clicked while scrolled right", () => {
  const clientWidth = 480;
  const maxScroll = scrollWidth - clientWidth;
  const target = computeScrollTargetForItem(items, 0, {
    clientWidth,
    scrollWidth,
    scrollLeft: 300,
    fadeSize,
  });
  assert.equal(target, 0);
  assert.equal(
    isItemInFadeZone(items[0], target!, clientWidth, maxScroll, fadeSize),
    false,
  );
  assert.equal(
    isItemInFadeZone(items[1], target!, clientWidth, maxScroll, fadeSize),
    false,
  );
});

test("handles narrow container where only clicked item can be centered", () => {
  const narrowItems = [
    { left: 0, width: 140 },
    { left: 140, width: 140 },
    { left: 280, width: 140 },
  ];
  // clientWidth = 260, sharp interior = [56, 204] (148px wide, fits 140px item)
  const target = computeScrollTargetForItem(narrowItems, 1, {
    clientWidth: 260,
    scrollWidth: 420,
    scrollLeft: 0,
    fadeSize,
  });
  assert.equal(target, 80); // centered: 140 + 70 - 130 = 80
  assert.equal(
    isItemInFadeZone(narrowItems[1], target!, 260, 420 - 260, fadeSize),
    false,
  );
});

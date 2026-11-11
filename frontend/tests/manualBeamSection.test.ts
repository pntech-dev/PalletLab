import { strict as assert } from "node:assert";
import { test } from "node:test";
import { manualSectionForSupport } from "../src/manualBeamSection.ts";
import type { ViewportBeam } from "../src/PalletViewport";

const layers = [
  { id: "bottom", direction: { beam_height: 70, beam_width: 50 } },
  { id: "middle", direction: { beam_height: 100, beam_width: 80 } },
  { id: "top", direction: { beam_height: 25, beam_width: 100 } },
];
const fallback = { height: 1, width: 2 };

test("uses the target layer default even when the support was edited manually", () => {
  const support = { layerId: "bottom", physicalLayerId: "bottom", size: [900, 30, 40] } as ViewportBeam;
  assert.deepEqual(manualSectionForSupport(layers, support, fallback), { height: 100, width: 80 });
});

test("resolves the physical layer of a manually added support", () => {
  const support = { layerId: "manual-1", physicalLayerId: "middle", size: [900, 30, 40] } as ViewportBeam;
  assert.deepEqual(manualSectionForSupport(layers, support, fallback), { height: 25, width: 100 });
});

test("does not pick an unrelated layer for an unknown or top support", () => {
  assert.deepEqual(manualSectionForSupport(layers, { physicalLayerId: "missing" } as ViewportBeam, fallback), fallback);
  assert.deepEqual(manualSectionForSupport(layers, { physicalLayerId: "top" } as ViewportBeam, fallback), fallback);
});

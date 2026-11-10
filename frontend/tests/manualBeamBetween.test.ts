import { strict as assert } from "node:assert";
import { test } from "node:test";
import { betweenFaces } from "../src/manualBeamBetween.ts";
import type { ViewportBeam } from "../src/PalletViewport";

function beam(id: string, x: number, y: number): ViewportBeam {
  return { layerId: id, layerIndex: 0, center: [x, y, 0], size: [100, 100, 70] } as ViewportBeam;
}

test("center between facing X and Y faces reports distance from the origin", () => {
  const first = { beam: beam("a", 100, 100), face: "x_max" as const };
  const second = { beam: beam("b", 900, 900), face: "x_min" as const };
  assert.deepEqual(betweenFaces(first, second, 50), { center: 500, baseDistance: 475 });
  assert.deepEqual(betweenFaces(second, first, 50), { center: 500, baseDistance: 475 });
  assert.deepEqual(betweenFaces({ ...first, face: "y_max" }, { ...second, face: "y_min" }, 50),
    { center: 500, baseDistance: 475 });
  assert.deepEqual(betweenFaces({ beam: beam("c", -900, 0), face: "x_max" },
    { beam: beam("d", -100, 0), face: "x_min" }, 50), { center: -500, baseDistance: -475 });
});

test("rejects faces that point away, are on one beam, or leave too little space", () => {
  const first = { beam: beam("a", 100, 100), face: "x_max" as const };
  const second = { beam: beam("b", 900, 900), face: "x_min" as const };
  assert.equal(betweenFaces(first, { ...second, face: "x_max" }, 50), null);
  assert.equal(betweenFaces(first, { ...first, face: "x_min" }, 50), null);
  assert.equal(betweenFaces(first, second, 701), null);
});

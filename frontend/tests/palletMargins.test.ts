import { strict as assert } from "node:assert";
import { test } from "node:test";
import { changePalletMargin, marginLinks, palletMargins, toggleMarginLink } from "../src/palletMargins.ts";

const direction = (positions: number[] | null) => ({
  beam_height: 70, beam_width: 50, support_distances: [500],
  first_edge_to_support: 100, last_support_to_edge: 100,
  margin_start: 100, margin_end: 100, round_pallet_size: false,
  rounding_step: 5 as const, support_positions: positions,
});

function example() {
  const x = direction([200, 700]);
  const y = direction([250, 750]);
  return { pallet: { length: x, width: y, layers: [
    { id: "x", axis: "length" as const, direction: x },
    { id: "y", axis: "width" as const, direction: y },
  ], upper_layer: "width" as const, material_id: "spruce", manual_beams: [{ start_point: [250, 300, 70] }] },
  view: { camera: "top" as const, show_length_dimensions: true, show_width_dimensions: true, hidden_layer_ids: [] } };
}

test("linked margins change together only on their own axis", () => {
  const project = example();
  assert.deepEqual(marginLinks(project), [true, true]);
  const changed = changePalletMargin(project, 0, 200);
  assert.deepEqual(palletMargins(changed), [200, 200, 100, 100]);
  assert.deepEqual(changed.pallet.layers[0].direction.support_positions, [300, 800]);
  assert.deepEqual(changed.pallet.layers[1].direction.support_positions, [250, 750]);
  assert.deepEqual(changed.pallet.manual_beams?.[0].start_point, [350, 300, 70]);
  assert.deepEqual(project.pallet.layers[0].direction.support_positions, [200, 700]);
});

test("unlink, change independently, and relink to the first value", () => {
  const unlinked = toggleMarginLink(example(), 1);
  assert.deepEqual(marginLinks(unlinked), [true, false]);
  const changed = changePalletMargin(unlinked, 3, 150);
  assert.deepEqual(palletMargins(changed), [100, 100, 100, 150]);
  assert.deepEqual(changed.pallet.layers[1].direction.support_positions, [250, 750]);
  const relinked = toggleMarginLink(changed, 1);
  assert.deepEqual(palletMargins(relinked), [100, 100, 100, 100]);
  const moved = changePalletMargin(relinked, 2, 125);
  assert.deepEqual(palletMargins(moved), [100, 100, 125, 125]);
  assert.deepEqual(moved.pallet.layers[1].direction.support_positions, [275, 775]);
  assert.deepEqual(moved.pallet.manual_beams?.[0].start_point, [250, 325, 70]);
});

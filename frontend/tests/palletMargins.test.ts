import { strict as assert } from "node:assert";
import { test } from "node:test";
import { changePalletMargin, marginLinks, MARGIN_PAIRS, palletMargins, toggleMarginLink } from "../src/palletMargins.ts";

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
    { id: "x2", axis: "length" as const, direction: x },
  ], upper_layer: "width" as const, material_id: "spruce", manual_beams: [{ start_point: [250, 300, 70] }] },
  view: { camera: "top" as const, show_length_dimensions: true, show_width_dimensions: true, hidden_layer_ids: [] } };
}

test("each visible side changes its physical axis and endpoint", () => {
  assert.deepEqual(MARGIN_PAIRS.map(({ first, second, link }) => [first, second, link]), [[0, 1, 0], [2, 3, 1]]);
  const project = toggleMarginLink(toggleMarginLink(example(), 0), 1);
  for (const [index, expected, xStart, xEnd, yStart, yEnd] of [
    [MARGIN_PAIRS[0].first, [130, 100, 100, 100], 130, 100, 100, 100],
    [MARGIN_PAIRS[0].second, [100, 130, 100, 100], 100, 130, 100, 100],
    [MARGIN_PAIRS[1].first, [100, 100, 130, 100], 100, 100, 130, 100],
    [MARGIN_PAIRS[1].second, [100, 100, 100, 130], 100, 100, 100, 130],
  ] as const) {
    const changed = changePalletMargin(project, index, 130);
    assert.deepEqual(palletMargins(changed), expected);
    for (const layer of changed.pallet.layers) {
      assert.equal(layer.direction.margin_start, layer.axis === "length" ? xStart : yStart);
      assert.equal(layer.direction.margin_end, layer.axis === "length" ? xEnd : yEnd);
    }
    assert.deepEqual(changed.pallet.manual_beams?.[0].start_point, [250 + xStart - 100, 300 + yStart - 100, 70]);
  }
});

test("links affect only their physical axis and persist in X/Y order", () => {
  const project = example();
  assert.deepEqual(marginLinks(project), [true, true]);
  const left = changePalletMargin(project, MARGIN_PAIRS[0].first, 200);
  assert.deepEqual(palletMargins(left), [200, 200, 100, 100]);
  assert.deepEqual(left.pallet.layers[0].direction.support_positions, [300, 800]);
  assert.deepEqual(left.pallet.layers[1].direction.support_positions, [250, 750]);
  assert.deepEqual(left.pallet.manual_beams?.[0].start_point, [350, 300, 70]);
  const top = changePalletMargin(project, MARGIN_PAIRS[1].first, 150);
  assert.deepEqual(palletMargins(top), [100, 100, 150, 150]);
  assert.deepEqual(top.pallet.manual_beams?.[0].start_point, [250, 350, 70]);
  assert.deepEqual(project.pallet.layers[0].direction.support_positions, [200, 700]);
});

test("relink copies the first displayed value to the second", () => {
  const unlinked = toggleMarginLink(example(), MARGIN_PAIRS[1].link);
  const changed = changePalletMargin(unlinked, MARGIN_PAIRS[1].second, 150);
  assert.deepEqual(palletMargins(changed), [100, 100, 100, 150]);
  const relinked = toggleMarginLink(changed, MARGIN_PAIRS[1].link);
  assert.deepEqual(palletMargins(relinked), [100, 100, 100, 100]);
  assert.deepEqual(relinked.pallet.manual_beams?.[0].start_point, [250, 300, 70]);
});

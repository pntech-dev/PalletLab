import { test } from "node:test";
import { strict as assert } from "node:assert";
import { DEFAULT_SETTINGS, projectWithDefaults, projectWithChangedDefaults, applyDefaultsIfUnmodified } from "../src/appSettings.ts";
import type { Project } from "../src/App";

function project(): Project {
  const direction = { beam_height: 70, beam_width: 50, support_distances: [500], first_edge_to_support: 100,
    last_support_to_edge: 100, margin_start: 50, margin_end: 50, round_pallet_size: true, rounding_step: 50 as const };
  return { pallet: { length: direction, width: direction, layers: [{ id: "a", axis: "length", direction }], upper_layer: "length", material_id: "pine" },
    view: { camera: "top", show_length_dimensions: false, show_width_dimensions: false, show_grid: false, hidden_layer_ids: [], locked_layer_ids: [] } };
}

test("new project defaults update every layer and scene without mutating the original", () => {
  const original = project();
  const result = projectWithDefaults(original, { ...DEFAULT_SETTINGS, rounding: "none", camera: "front", showGrid: true });
  assert.equal(result.pallet.length.round_pallet_size, false);
  assert.equal(result.pallet.layers[0].direction.round_pallet_size, false);
  assert.equal(result.view.camera, "front");
  assert.equal(result.view.show_grid, true);
  assert.equal(original.pallet.length.round_pallet_size, true);
  assert.equal(original.view.camera, "top");
});

test("changing an application preference does not overwrite unchanged project defaults", () => {
  const original = project();
  const updated = projectWithChangedDefaults(original, DEFAULT_SETTINGS, { ...DEFAULT_SETTINGS, autosaveEnabled: false });
  assert.deepEqual(updated, original);
  const changed = projectWithChangedDefaults(original, DEFAULT_SETTINGS, { ...DEFAULT_SETTINGS, rounding: "5" });
  assert.equal(changed.pallet.layers[0].direction.rounding_step, 5);
  assert.deepEqual(changed.view, original.view);
});


test("new defaults apply only to a project unchanged since opening or creation", () => {
  const current = project();
  const baseline = JSON.stringify(current);
  const next = { ...DEFAULT_SETTINGS, rounding: "5" as const };
  assert.equal(applyDefaultsIfUnmodified(current, baseline, DEFAULT_SETTINGS, next)?.pallet.layers[0].direction.rounding_step, 5);
  const modified = { ...current, pallet: { ...current.pallet, material_id: "oak" } };
  assert.equal(applyDefaultsIfUnmodified(modified, baseline, DEFAULT_SETTINGS, next), null);
  assert.equal(applyDefaultsIfUnmodified(current, null, DEFAULT_SETTINGS, next), null);
});

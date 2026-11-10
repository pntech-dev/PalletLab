import { strict as assert } from "node:assert";
import { test } from "node:test";
import { remainingImportFeedback, stepImportPhase } from "../src/stepImportUi.ts";

test("the import dialog remains open while cached or imported geometry is prepared", () => {
  assert.equal(stepImportPhase("running", false, false), "importing");
  assert.equal(stepImportPhase("cancelling", false, false), "importing");
  assert.equal(stepImportPhase("completed", false, false), "preparing");
  assert.equal(stepImportPhase("completed", true, false), null);
  assert.equal(stepImportPhase("completed", false, true), null);
  assert.equal(stepImportPhase("failed", false, false), null);
});

test("fast preparation shows feedback briefly without delaying long imports", () => {
  assert.equal(remainingImportFeedback(1000, 1100), 300);
  assert.equal(remainingImportFeedback(1000, 1500), 0);
});

import { strict as assert } from "node:assert";
import { test } from "node:test";
import { resolveUpdateCheckResult } from "../src/design/updateCheckState.ts";

test("maps current update state to no-updates feedback phase", () => {
  assert.equal(resolveUpdateCheckResult("current"), "none");
});

test("maps available and ready update states to found-update feedback phase", () => {
  assert.equal(resolveUpdateCheckResult("available"), "found");
  assert.equal(resolveUpdateCheckResult("ready"), "found");
});

test("returns to idle on failure, unavailable, or idle states", () => {
  assert.equal(resolveUpdateCheckResult("check_failed"), "idle");
  assert.equal(resolveUpdateCheckResult("unavailable"), "idle");
  assert.equal(resolveUpdateCheckResult("idle"), "idle");
});

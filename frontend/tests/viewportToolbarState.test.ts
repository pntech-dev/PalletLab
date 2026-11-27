import { strict as assert } from "node:assert";
import { test } from "node:test";
import { nextToolbarManualExpanded } from "../src/viewportToolbarState.ts";

test("resumes auto mode when returning toolbar to default state for current viewport mode", () => {
  // Normal mode (viewportExpanded = false): user expands, then collapses back to default.
  let manual: boolean | null = nextToolbarManualExpanded(false, false);
  assert.equal(manual, true);

  manual = nextToolbarManualExpanded(manual ?? false, false);
  assert.equal(manual, null);

  // Entering fullscreen now follows automatic mode and expands the toolbar.
  assert.equal(manual ?? true, true);
});

test("keeps manual override across fullscreen toggles when different from default", () => {
  // Normal mode: user expands and enters fullscreen without collapsing.
  const manual = nextToolbarManualExpanded(false, false);
  assert.equal(manual, true);

  // Toggling fullscreen on then off preserves expanded state.
  assert.equal(manual ?? true, true);
  assert.equal(manual ?? false, true);

  // Fullscreen mode: user collapses toolbar, then restores it to fullscreen default.
  const collapsedInFullscreen = nextToolbarManualExpanded(true, true);
  assert.equal(collapsedInFullscreen, false);
  assert.equal(collapsedInFullscreen ?? false, false);

  const restoredInFullscreen = nextToolbarManualExpanded(false, true);
  assert.equal(restoredInFullscreen, null);
  assert.equal(restoredInFullscreen ?? false, false);
});

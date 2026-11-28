import { strict as assert } from "node:assert";
import { test } from "node:test";
import {
  computeViewportToolbarLayout,
  nextToolbarManualExpanded,
  type ViewportToolbarLayoutInput,
} from "../src/viewportToolbarState.ts";

const baseInput: ViewportToolbarLayoutInput = {
  viewportExpanded: false,
  toolbarManualExpanded: null,
  hasSummary: true,
  availableWidth: 1000,
  collapsedBarWidth: 260,
  expandedBarWidth: 720,
  endWidth: 162,
  fullSummaryWidth: 420,
  compactSummaryWidth: 250,
};

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

test("normal viewport keeps separated collapsed toolbar when it fits", () => {
  const layout = computeViewportToolbarLayout({
    ...baseInput,
    availableWidth: 600,
  });
  assert.deepEqual(layout, {
    unified: false,
    labelsVisible: false,
    scrollableTools: false,
    showCollapseToggle: true,
    summaryMode: "none",
  });
});

test("normal viewport merges with labels and hides collapse button when collapsed toolbar overflows", () => {
  // collapsedBarWidth (260) + minSpacer (28) + endWidth (162) = 450
  const layout = computeViewportToolbarLayout({
    ...baseInput,
    availableWidth: 440,
  });
  assert.deepEqual(layout, {
    unified: true,
    labelsVisible: true,
    scrollableTools: true,
    showCollapseToggle: false,
    summaryMode: "none",
  });
});

test("normal viewport merges with collapse button before combobox when expanded labels overflow but collapsed fits", () => {
  // collapsed fits (450 <= 700), expanded does not (720 + 28 + 162 = 910 > 700)
  const layout = computeViewportToolbarLayout({
    ...baseInput,
    toolbarManualExpanded: true,
    availableWidth: 700,
  });
  assert.deepEqual(layout, {
    unified: true,
    labelsVisible: true,
    scrollableTools: true,
    showCollapseToggle: true,
    summaryMode: "none",
  });
});

test("normal viewport keeps separated expanded toolbar when expanded labels fit", () => {
  const layout = computeViewportToolbarLayout({
    ...baseInput,
    toolbarManualExpanded: true,
    availableWidth: 920,
  });
  assert.deepEqual(layout, {
    unified: false,
    labelsVisible: true,
    scrollableTools: false,
    showCollapseToggle: true,
    summaryMode: "none",
  });
});

test("fullscreen viewport cascades summary: full in toolbar -> compact in toolbar -> compact above bottom controls", () => {
  // Full summary: 720 + 16 + 420 + 162 = 1318
  assert.deepEqual(
    computeViewportToolbarLayout({
      ...baseInput,
      viewportExpanded: true,
      availableWidth: 1350,
    }),
    {
      unified: false,
      labelsVisible: true,
      scrollableTools: false,
      showCollapseToggle: true,
      summaryMode: "toolbar-full",
    },
  );

  // Compact summary in toolbar: 720 + 16 + 250 + 162 = 1148
  assert.deepEqual(
    computeViewportToolbarLayout({
      ...baseInput,
      viewportExpanded: true,
      availableWidth: 1200,
    }),
    {
      unified: false,
      labelsVisible: true,
      scrollableTools: false,
      showCollapseToggle: true,
      summaryMode: "toolbar-compact",
    },
  );

  // Moved to bottom, expanded toolbar fits (720 + 28 + 162 = 910)
  assert.deepEqual(
    computeViewportToolbarLayout({
      ...baseInput,
      viewportExpanded: true,
      availableWidth: 1000,
    }),
    {
      unified: false,
      labelsVisible: true,
      scrollableTools: false,
      showCollapseToggle: true,
      summaryMode: "bottom-compact",
    },
  );
});

test("fullscreen viewport merges with collapse button when expanded overflows but collapsed fits, and removes it when collapsed also overflows", () => {
  // Expanded overflows (910 > 700), collapsed fits (450 <= 700)
  assert.deepEqual(
    computeViewportToolbarLayout({
      ...baseInput,
      viewportExpanded: true,
      availableWidth: 700,
    }),
    {
      unified: true,
      labelsVisible: true,
      scrollableTools: true,
      showCollapseToggle: true,
      summaryMode: "bottom-compact",
    },
  );

  // Even collapsed overflows (450 > 400): expand labels, merge, no collapse button
  assert.deepEqual(
    computeViewportToolbarLayout({
      ...baseInput,
      viewportExpanded: true,
      availableWidth: 400,
    }),
    {
      unified: true,
      labelsVisible: true,
      scrollableTools: true,
      showCollapseToggle: false,
      summaryMode: "bottom-compact",
    },
  );
});

test("fullscreen viewport respects manual collapse when collapsed fits and forces labels when collapsed overflows", () => {
  // Manually collapsed and fits with bottom summary
  assert.deepEqual(
    computeViewportToolbarLayout({
      ...baseInput,
      viewportExpanded: true,
      toolbarManualExpanded: false,
      availableWidth: 600,
    }),
    {
      unified: false,
      labelsVisible: false,
      scrollableTools: false,
      showCollapseToggle: true,
      summaryMode: "bottom-compact",
    },
  );

  // Manually collapsed, narrow screen where even collapsed overflows -> forced unified + labels, no toggle
  assert.deepEqual(
    computeViewportToolbarLayout({
      ...baseInput,
      viewportExpanded: true,
      toolbarManualExpanded: false,
      availableWidth: 400,
    }),
    {
      unified: true,
      labelsVisible: true,
      scrollableTools: true,
      showCollapseToggle: false,
      summaryMode: "bottom-compact",
    },
  );
});

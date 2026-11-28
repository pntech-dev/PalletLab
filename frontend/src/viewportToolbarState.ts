export type ViewportToolbarSummaryMode =
    | "none"
    | "toolbar-full"
    | "toolbar-compact"
    | "bottom-compact";

export type ViewportToolbarLayout = {
    unified: boolean;
    labelsVisible: boolean;
    scrollableTools: boolean;
    showCollapseToggle: boolean;
    summaryMode: ViewportToolbarSummaryMode;
};

export type ViewportToolbarLayoutInput = {
    viewportExpanded: boolean;
    toolbarManualExpanded: boolean | null;
    hasSummary: boolean;
    availableWidth: number;
    collapsedBarWidth: number;
    expandedBarWidth: number;
    endWidth: number;
    fullSummaryWidth: number;
    compactSummaryWidth: number;
    minSpacerWidth?: number;
    summaryGapWidth?: number;
};

/** Computes the manual override after toggling the viewport toolbar, returning null when back to mode default. */
export function nextToolbarManualExpanded(
    currentToolbarExpanded: boolean,
    viewportExpanded: boolean,
): boolean | null {
    const next = !currentToolbarExpanded;
    return next === viewportExpanded ? null : next;
}

/** Resolves whether the viewport toolbar should merge, scroll, toggle labels, or relocate the summary. */
export function computeViewportToolbarLayout(
    input: ViewportToolbarLayoutInput,
): ViewportToolbarLayout {
    const {
        viewportExpanded,
        toolbarManualExpanded,
        hasSummary,
        availableWidth,
        collapsedBarWidth,
        expandedBarWidth,
        endWidth,
        fullSummaryWidth,
        compactSummaryWidth,
        minSpacerWidth = 28,
        summaryGapWidth = 16,
    } = input;

    const preferredExpanded = toolbarManualExpanded ?? viewportExpanded;

    if (availableWidth <= 0) {
        return {
            unified: false,
            labelsVisible: preferredExpanded,
            scrollableTools: false,
            showCollapseToggle: true,
            summaryMode:
                viewportExpanded && hasSummary ? "toolbar-full" : "none",
        };
    }

    const collapsedFits =
        collapsedBarWidth + minSpacerWidth + endWidth <= availableWidth;
    const expandedFits =
        expandedBarWidth + minSpacerWidth + endWidth <= availableWidth;

    if (viewportExpanded && hasSummary) {
        const activeBarWidth = preferredExpanded
            ? expandedBarWidth
            : collapsedBarWidth;
        if (
            activeBarWidth + summaryGapWidth + fullSummaryWidth + endWidth <=
            availableWidth
        ) {
            return {
                unified: false,
                labelsVisible: preferredExpanded,
                scrollableTools: false,
                showCollapseToggle: true,
                summaryMode: "toolbar-full",
            };
        }
        if (
            activeBarWidth + summaryGapWidth + compactSummaryWidth + endWidth <=
            availableWidth
        ) {
            return {
                unified: false,
                labelsVisible: preferredExpanded,
                scrollableTools: false,
                showCollapseToggle: true,
                summaryMode: "toolbar-compact",
            };
        }
    }

    const summaryMode: ViewportToolbarSummaryMode =
        viewportExpanded && hasSummary ? "bottom-compact" : "none";

    if (!collapsedFits) {
        return {
            unified: true,
            labelsVisible: true,
            scrollableTools: true,
            showCollapseToggle: false,
            summaryMode,
        };
    }

    if (!preferredExpanded) {
        return {
            unified: false,
            labelsVisible: false,
            scrollableTools: false,
            showCollapseToggle: true,
            summaryMode,
        };
    }

    if (expandedFits) {
        return {
            unified: false,
            labelsVisible: true,
            scrollableTools: false,
            showCollapseToggle: true,
            summaryMode,
        };
    }

    return {
        unified: true,
        labelsVisible: true,
        scrollableTools: true,
        showCollapseToggle: true,
        summaryMode,
    };
}

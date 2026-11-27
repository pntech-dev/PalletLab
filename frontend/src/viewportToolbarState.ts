/** Computes the manual override after toggling the viewport toolbar, returning null when back to mode default. */
export function nextToolbarManualExpanded(
  currentToolbarExpanded: boolean,
  viewportExpanded: boolean,
): boolean | null {
  const next = !currentToolbarExpanded;
  return next === viewportExpanded ? null : next;
}

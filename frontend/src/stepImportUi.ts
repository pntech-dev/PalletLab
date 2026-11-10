/** Keep the import dialog open through geometry preparation, including cache hits. */
export function stepImportPhase(state: string | undefined, hasModel: boolean, hasError: boolean): "importing" | "preparing" | null {
  if (state === "running" || state === "cancelling") return "importing";
  if (state === "completed" && !hasModel && !hasError) return "preparing";
  return null;
}

/** A fast cache hit should still give the user visible feedback. */
export function remainingImportFeedback(startedAt: number, now: number): number {
  return Math.max(0, 400 - (now - startedAt));
}

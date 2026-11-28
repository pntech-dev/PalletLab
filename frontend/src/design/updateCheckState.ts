export type UpdateCheckState =
    | "idle"
    | "unavailable"
    | "checking"
    | "current"
    | "check_failed"
    | "available"
    | "downloading"
    | "ready"
    | "installing"
    | "failed";

export type UpdateCheckPhase = "idle" | "checking" | "none" | "found";

export function resolveUpdateCheckResult(
    state: UpdateCheckState,
): Exclude<UpdateCheckPhase, "checking"> {
    if (state === "current") return "none";
    if (state === "available" || state === "ready") return "found";
    return "idle";
}

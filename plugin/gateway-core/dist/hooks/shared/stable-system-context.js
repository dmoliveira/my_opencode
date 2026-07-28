export const RUNTIME_SESSION_CONTEXT_MARKER = "runtime_session_context:";
export const RUNTIME_CONCISE_CONTEXT_MARKER = "runtime_concise_mode:";
const RUNTIME_SYSTEM_MARKERS = [
    RUNTIME_SESSION_CONTEXT_MARKER,
    RUNTIME_CONCISE_CONTEXT_MARKER,
];
export function managedRuntimeSystemMarker(entry) {
    const firstLine = entry.split("\n", 1)[0] ?? "";
    return RUNTIME_SYSTEM_MARKERS.find((marker) => firstLine.startsWith(marker)) ?? null;
}
// Inserts stable repository guidance before per-session runtime context so providers
// can reuse the longest common system-prompt prefix across sessions and worktrees.
export function insertStableSystemContext(system, context) {
    const insertionIndex = system.findIndex((entry) => managedRuntimeSystemMarker(entry) !== null);
    if (insertionIndex < 0) {
        system.push(context);
        return;
    }
    system.splice(insertionIndex, 0, context);
}
// Keeps filesystem metadata out of model-visible prompt text and removes controls
// that could alter the structure of an injected instruction block.
export function stableContextLabel(value) {
    return value.replace(/[\u0000-\u001F\u007F]/g, " ").trim() || "local-context";
}

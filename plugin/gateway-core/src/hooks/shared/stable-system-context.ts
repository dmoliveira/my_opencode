const RUNTIME_SYSTEM_MARKERS = ["runtime_session_context:", "runtime_concise_mode:"]

// Inserts stable repository guidance before per-session runtime context so providers
// can reuse the longest common system-prompt prefix across sessions and worktrees.
export function insertStableSystemContext(system: string[], context: string): void {
  const insertionIndex = system.findIndex((entry) =>
    RUNTIME_SYSTEM_MARKERS.some((marker) => entry.includes(marker)),
  )
  if (insertionIndex < 0) {
    system.push(context)
    return
  }
  system.splice(insertionIndex, 0, context)
}

// Keeps filesystem metadata out of model-visible prompt text and removes controls
// that could alter the structure of an injected instruction block.
export function stableContextLabel(value: string): string {
  return value.replace(/[\u0000-\u001F\u007F]/g, " ").trim() || "local-context"
}

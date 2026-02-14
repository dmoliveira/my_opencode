import { mkdirSync, readFileSync, unlinkSync, writeFileSync, existsSync } from "node:fs"
import { dirname, join } from "node:path"
import { DEFAULT_STATE_FILE } from "./constants.js"
import type { AutopilotLoopState } from "./types.js"

// Resolves absolute loop state file path for a project directory.
export function resolveStatePath(directory: string, stateFile?: string): string {
  return join(directory, stateFile ?? DEFAULT_STATE_FILE)
}

// Loads persisted loop state from disk.
export function loadState(directory: string, stateFile?: string): AutopilotLoopState | null {
  const path = resolveStatePath(directory, stateFile)
  if (!existsSync(path)) {
    return null
  }
  try {
    const parsed = JSON.parse(readFileSync(path, "utf-8")) as unknown
    if (!parsed || typeof parsed !== "object") {
      return null
    }
    const state = parsed as Partial<AutopilotLoopState>
    if (!state.sessionId || !state.prompt) {
      return null
    }
    return {
      active: state.active === true,
      sessionId: String(state.sessionId),
      prompt: String(state.prompt),
      iteration: Number(state.iteration ?? 1),
      maxIterations: Number(state.maxIterations ?? 100),
      completionMode: state.completionMode === "objective" ? "objective" : "promise",
      completionPromise: String(state.completionPromise ?? "DONE"),
      startedAt: String(state.startedAt ?? new Date().toISOString()),
    }
  } catch {
    return null
  }
}

// Persists loop state to disk.
export function saveState(directory: string, state: AutopilotLoopState, stateFile?: string): void {
  const path = resolveStatePath(directory, stateFile)
  mkdirSync(dirname(path), { recursive: true })
  writeFileSync(path, `${JSON.stringify(state, null, 2)}\n`, "utf-8")
}

// Deletes loop state file if present.
export function clearState(directory: string, stateFile?: string): void {
  const path = resolveStatePath(directory, stateFile)
  if (existsSync(path)) {
    unlinkSync(path)
  }
}

// Increments persisted loop iteration and returns updated state.
export function incrementIteration(
  directory: string,
  state: AutopilotLoopState,
  stateFile?: string,
): AutopilotLoopState {
  const updated: AutopilotLoopState = {
    ...state,
    iteration: state.iteration + 1,
  }
  saveState(directory, updated, stateFile)
  return updated
}

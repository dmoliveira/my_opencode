import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs"
import { dirname, join } from "node:path"
import type { GatewayState } from "./types.js"

// Declares default gateway state file path.
export const DEFAULT_STATE_PATH = ".opencode/gateway-core.state.json"

// Resolves absolute gateway state path for the project directory.
export function resolveGatewayStatePath(directory: string, relativePath?: string): string {
  return join(directory, relativePath ?? DEFAULT_STATE_PATH)
}

// Loads gateway runtime state or returns null when unavailable.
export function loadGatewayState(directory: string, relativePath?: string): GatewayState | null {
  const path = resolveGatewayStatePath(directory, relativePath)
  if (!existsSync(path)) {
    return null
  }
  try {
    const raw = JSON.parse(readFileSync(path, "utf-8")) as unknown
    if (!raw || typeof raw !== "object") {
      return null
    }
    const parsed = raw as Partial<GatewayState>
    return {
      activeLoop: parsed.activeLoop ?? null,
      lastUpdatedAt: String(parsed.lastUpdatedAt ?? new Date().toISOString()),
    }
  } catch {
    return null
  }
}

// Saves gateway runtime state to disk.
export function saveGatewayState(
  directory: string,
  state: GatewayState,
  relativePath?: string,
): void {
  const path = resolveGatewayStatePath(directory, relativePath)
  mkdirSync(dirname(path), { recursive: true })
  writeFileSync(path, `${JSON.stringify(state, null, 2)}\n`, "utf-8")
}

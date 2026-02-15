import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
// Declares default gateway state file path.
export const DEFAULT_STATE_PATH = ".opencode/gateway-core.state.json";
// Resolves absolute gateway state path for the project directory.
export function resolveGatewayStatePath(directory, relativePath) {
    return join(directory, relativePath ?? DEFAULT_STATE_PATH);
}
// Loads gateway runtime state or returns null when unavailable.
export function loadGatewayState(directory, relativePath) {
    const path = resolveGatewayStatePath(directory, relativePath);
    if (!existsSync(path)) {
        return null;
    }
    try {
        const raw = JSON.parse(readFileSync(path, "utf-8"));
        if (!raw || typeof raw !== "object") {
            return null;
        }
        const parsed = raw;
        return {
            activeLoop: parsed.activeLoop ?? null,
            lastUpdatedAt: String(parsed.lastUpdatedAt ?? new Date().toISOString()),
            source: typeof parsed.source === "string" ? parsed.source : undefined,
        };
    }
    catch {
        return null;
    }
}
// Saves gateway runtime state to disk.
export function saveGatewayState(directory, state, relativePath) {
    const path = resolveGatewayStatePath(directory, relativePath);
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, `${JSON.stringify(state, null, 2)}\n`, "utf-8");
}
// Returns current UTC timestamp string in ISO-8601 format.
export function nowIso() {
    return new Date().toISOString();
}
// Marks active loop as inactive while preserving state metadata.
export function deactivateGatewayLoop(directory, reason, relativePath) {
    const state = loadGatewayState(directory, relativePath);
    if (!state?.activeLoop) {
        return state;
    }
    state.activeLoop.active = false;
    state.lastUpdatedAt = nowIso();
    const next = {
        ...state,
        source: reason,
    };
    saveGatewayState(directory, next, relativePath);
    return next;
}
// Cleans stale active loop state based on elapsed runtime age.
export function cleanupOrphanGatewayLoop(directory, maxAgeHours, relativePath) {
    const state = loadGatewayState(directory, relativePath);
    if (!state) {
        return { changed: false, reason: "state_missing", state: null };
    }
    if (!state.activeLoop || state.activeLoop.active !== true) {
        return { changed: false, reason: "not_active", state };
    }
    const startedAt = Date.parse(state.activeLoop.startedAt);
    if (!Number.isFinite(startedAt)) {
        const next = deactivateGatewayLoop(directory, "invalid_started_at", relativePath);
        return {
            changed: true,
            reason: "invalid_started_at",
            state: next,
        };
    }
    const elapsedMs = Date.now() - startedAt;
    const maxAgeMs = Math.max(1, maxAgeHours) * 60 * 60 * 1000;
    if (elapsedMs <= maxAgeMs) {
        return { changed: false, reason: "within_age_limit", state };
    }
    const next = deactivateGatewayLoop(directory, "stale_loop_deactivated", relativePath);
    return {
        changed: true,
        reason: "stale_loop_deactivated",
        state: next,
    };
}

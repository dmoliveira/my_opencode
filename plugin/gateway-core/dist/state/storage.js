import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
const VALID_CONCISE_MODES = new Set(["off", "lite", "full", "ultra", "review", "commit"]);
function parseConciseModeState(value) {
    if (!value || typeof value !== "object") {
        return null;
    }
    const record = value;
    const mode = String(record.mode ?? "").trim().toLowerCase();
    const sessionId = String(record.sessionId ?? "").trim();
    if (!VALID_CONCISE_MODES.has(mode)) {
        return null;
    }
    if (!sessionId) {
        return null;
    }
    return {
        mode: mode,
        source: String(record.source ?? "state"),
        sessionId,
        activatedAt: String(record.activatedAt ?? new Date().toISOString()),
        updatedAt: String(record.updatedAt ?? new Date().toISOString()),
    };
}
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
            conciseMode: parseConciseModeState(parsed.conciseMode),
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
    const existing = loadGatewayState(directory, relativePath);
    const payload = {
        activeLoop: state.activeLoop,
        conciseMode: state.conciseMode === undefined ? existing?.conciseMode ?? null : state.conciseMode,
        lastUpdatedAt: state.lastUpdatedAt,
        source: state.source,
    };
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, `${JSON.stringify(payload, null, 2)}\n`, "utf-8");
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

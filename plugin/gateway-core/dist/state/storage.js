import { GatewayStateProtocolError, LOCK_DIRECTORY_NAME, LOCK_POLL_MS, LOCK_RECOVERY_GUIDANCE, LOCK_TIMEOUT_MS, MAX_STATE_BYTES, OWNER_TOKEN_NAME, PRIVATE_DIRECTORY_MODE, PRIVATE_FILE_MODE, STAGE_PREFIX, STATE_DIRECTORY_NAME, STATE_FILE_NAME, STATE_RELATIVE_PATH, gatewayStateLockStatus, loadRawGatewayState, loadRawGatewayStateSnapshot, resolveLockPath, resolveStatePath, transactGatewayStateDomain, updateGatewayStateDomain, } from "./protocol.js";
const VALID_CONCISE_MODES = new Set(["off", "lite", "full", "ultra", "review", "commit"]);
const ACTIVE_SNAPSHOT = Symbol("gateway-active-snapshot");
export { GatewayStateProtocolError, LOCK_DIRECTORY_NAME, LOCK_POLL_MS, LOCK_RECOVERY_GUIDANCE, LOCK_TIMEOUT_MS, MAX_STATE_BYTES, OWNER_TOKEN_NAME, PRIVATE_DIRECTORY_MODE, PRIVATE_FILE_MODE, STAGE_PREFIX, STATE_DIRECTORY_NAME, STATE_FILE_NAME, gatewayStateLockStatus, loadRawGatewayState, resolveLockPath, transactGatewayStateDomain, updateGatewayStateDomain, };
// Declares the only supported gateway state file path.
export const DEFAULT_STATE_PATH = STATE_RELATIVE_PATH;
function isRecord(value) {
    return Boolean(value && typeof value === "object" && !Array.isArray(value));
}
function jsonSemanticallyEqual(left, right) {
    if (left === right) {
        return true;
    }
    if (Array.isArray(left) || Array.isArray(right)) {
        return (Array.isArray(left) &&
            Array.isArray(right) &&
            left.length === right.length &&
            left.every((value, index) => jsonSemanticallyEqual(value, right[index])));
    }
    if (!isRecord(left) || !isRecord(right)) {
        return false;
    }
    const leftKeys = Object.keys(left).sort();
    const rightKeys = Object.keys(right).sort();
    return (leftKeys.length === rightKeys.length &&
        leftKeys.every((key, index) => key === rightKeys[index] && jsonSemanticallyEqual(left[key], right[key])));
}
function parseConciseModeState(value) {
    if (!isRecord(value)) {
        return null;
    }
    const mode = String(value.mode ?? "").trim().toLowerCase();
    const sessionId = String(value.sessionId ?? "").trim();
    if (!VALID_CONCISE_MODES.has(mode) || !sessionId) {
        return null;
    }
    return {
        mode: mode,
        source: String(value.source ?? "state"),
        sessionId,
        activatedAt: String(value.activatedAt ?? new Date().toISOString()),
        updatedAt: String(value.updatedAt ?? new Date().toISOString()),
    };
}
function isNonnegativeInteger(value) {
    return Number.isSafeInteger(value) && Number(value) >= 0;
}
function cloneActiveLoop(value) {
    if (!isRecord(value)) {
        return null;
    }
    const completionMode = value.completionMode;
    const doneCriteria = value.doneCriteria;
    const ignoredCompletionCycles = value.ignoredCompletionCycles;
    if (typeof value.active !== "boolean" ||
        typeof value.sessionId !== "string" ||
        value.sessionId.trim().length === 0 ||
        typeof value.objective !== "string" ||
        (completionMode !== "promise" && completionMode !== "objective") ||
        typeof value.completionPromise !== "string" ||
        !isNonnegativeInteger(value.iteration) ||
        !isNonnegativeInteger(value.maxIterations) ||
        typeof value.startedAt !== "string" ||
        (doneCriteria !== undefined &&
            (!Array.isArray(doneCriteria) || doneCriteria.some((item) => typeof item !== "string"))) ||
        (ignoredCompletionCycles !== undefined && !isNonnegativeInteger(ignoredCompletionCycles))) {
        return null;
    }
    return {
        ...value,
        active: value.active,
        sessionId: value.sessionId,
        objective: value.objective,
        completionMode,
        completionPromise: value.completionPromise,
        iteration: value.iteration,
        maxIterations: value.maxIterations,
        startedAt: value.startedAt,
        ...(doneCriteria === undefined ? {} : { doneCriteria: [...doneCriteria] }),
        ...(ignoredCompletionCycles === undefined ? {} : { ignoredCompletionCycles }),
    };
}
function attachActiveSnapshot(state, active) {
    Object.defineProperty(state, ACTIVE_SNAPSHOT, {
        value: structuredClone(active),
        enumerable: false,
        configurable: true,
        writable: true,
    });
    return state;
}
function normalizeGatewayState(raw) {
    const activeLoop = cloneActiveLoop(raw.activeLoop);
    const state = {
        activeLoop,
        conciseMode: parseConciseModeState(raw.conciseMode),
        lastUpdatedAt: String(raw.lastUpdatedAt ?? new Date().toISOString()),
        source: typeof raw.source === "string" ? raw.source : undefined,
    };
    return attachActiveSnapshot(state, raw.activeLoop);
}
function assertFixedPath(relativePath) {
    if (relativePath !== undefined && relativePath !== DEFAULT_STATE_PATH) {
        throw new GatewayStateProtocolError("gateway_state_unsafe_target", "gateway state path is fixed and cannot be overridden", { phase: "preflight" });
    }
}
// Resolves the fixed gateway state path for the project directory.
export function resolveGatewayStatePath(directory, relativePath) {
    assertFixedPath(relativePath);
    return resolveStatePath(directory);
}
// Loads gateway runtime state without a process-local cache.
export function loadGatewayState(directory, relativePath) {
    assertFixedPath(relativePath);
    const snapshot = loadRawGatewayStateSnapshot(directory);
    return snapshot.exists ? normalizeGatewayState(snapshot.state) : null;
}
function rootUpdates(state) {
    const updates = {
        lastUpdatedAt: state.lastUpdatedAt,
    };
    if (state.source !== undefined) {
        updates.source = state.source;
    }
    return updates;
}
// Saves only the activeLoop domain; conciseMode and unknown fields remain lock-protected siblings.
export function saveGatewayState(directory, state, relativePath) {
    assertFixedPath(relativePath);
    const snapshotState = state;
    const hasExpected = Object.prototype.hasOwnProperty.call(snapshotState, ACTIVE_SNAPSHOT);
    const expected = snapshotState[ACTIVE_SNAPSHOT];
    const result = transactGatewayStateDomain(directory, "activeLoop", (current) => {
        if (hasExpected && !jsonSemanticallyEqual(current, expected)) {
            throw new GatewayStateProtocolError("gateway_state_target_changed", "active gateway loop changed after it was loaded", { phase: "mutate" });
        }
        return {
            value: state.activeLoop,
            mode: "replace",
            rootUpdates: rootUpdates(state),
        };
    });
    if (!result.commit) {
        throw new GatewayStateProtocolError("gateway_state_io_failed", "active gateway loop save produced no commit", { phase: "transaction" });
    }
    attachActiveSnapshot(state, result.state.activeLoop);
    return result.commit;
}
// Saves only the conciseMode domain for explicit cross-runtime callers.
export function saveGatewayConciseMode(directory, conciseMode, metadata) {
    const updates = {
        lastUpdatedAt: metadata.lastUpdatedAt,
    };
    if (metadata.source !== undefined) {
        updates.source = metadata.source;
    }
    const result = updateGatewayStateDomain(directory, "conciseMode", conciseMode ?? null, {
        mode: "replace",
        rootUpdates: updates,
    });
    if (!result.commit) {
        throw new GatewayStateProtocolError("gateway_state_io_failed", "gateway concise mode save produced no commit", { phase: "transaction" });
    }
    return result.commit;
}
// Returns current UTC timestamp string in ISO-8601 format.
export function nowIso() {
    return new Date().toISOString();
}
function normalizedTransactionState(raw) {
    return Object.keys(raw).length > 0 ? normalizeGatewayState(raw) : null;
}
// Marks active loop as inactive through one lock-held conditional transaction.
export function deactivateGatewayLoop(directory, reason, relativePath) {
    assertFixedPath(relativePath);
    const result = transactGatewayStateDomain(directory, "activeLoop", (current) => {
        if (!isRecord(current)) {
            return null;
        }
        return {
            value: { active: false },
            mode: "patch",
            rootUpdates: { lastUpdatedAt: nowIso(), source: reason },
        };
    });
    return normalizedTransactionState(result.state);
}
// Cleans stale active loop state through one lock-held predicate and mutation.
export function cleanupOrphanGatewayLoop(directory, maxAgeHours, relativePath) {
    assertFixedPath(relativePath);
    let reason = "state_missing";
    const result = transactGatewayStateDomain(directory, "activeLoop", (current, raw) => {
        if (Object.keys(raw).length === 0) {
            reason = "state_missing";
            return null;
        }
        if (!isRecord(current) || current.active !== true) {
            reason = "not_active";
            return null;
        }
        const startedAt = Date.parse(String(current.startedAt ?? ""));
        if (!Number.isFinite(startedAt)) {
            reason = "invalid_started_at";
            return {
                value: { active: false },
                mode: "patch",
                rootUpdates: { lastUpdatedAt: nowIso(), source: reason },
            };
        }
        const elapsedMs = Date.now() - startedAt;
        const maxAgeMs = Math.max(1, maxAgeHours) * 60 * 60 * 1000;
        if (elapsedMs <= maxAgeMs) {
            reason = "within_age_limit";
            return null;
        }
        reason = "stale_loop_deactivated";
        return {
            value: { active: false },
            mode: "patch",
            rootUpdates: { lastUpdatedAt: nowIso(), source: reason },
        };
    });
    return {
        changed: result.changed,
        reason,
        state: normalizedTransactionState(result.state),
    };
}

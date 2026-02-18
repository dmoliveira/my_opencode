import { writeGatewayEventAudit } from "../../audit/event-audit.js";
function resolveSessionId(payload) {
    const candidates = [
        payload.input?.sessionID,
        payload.input?.sessionId,
        payload.properties?.sessionID,
        payload.properties?.sessionId,
        payload.properties?.info?.id,
    ];
    for (const value of candidates) {
        if (typeof value === "string" && value.trim()) {
            return value.trim();
        }
    }
    return "";
}
function pruneStates(states, maxEntries) {
    if (states.size <= maxEntries) {
        return;
    }
    let oldestKey = "";
    let oldestAt = Number.POSITIVE_INFINITY;
    for (const [key, state] of states.entries()) {
        if (state.lastSeenAtMs < oldestAt) {
            oldestAt = state.lastSeenAtMs;
            oldestKey = key;
        }
    }
    if (oldestKey) {
        states.delete(oldestKey);
    }
}
function formatDuration(ms) {
    if (ms < 1000) {
        return `${ms}ms`;
    }
    return `${(ms / 1000).toFixed(1)}s`;
}
export function createLongTurnWatchdogHook(options) {
    const states = new Map();
    const now = options.now ?? (() => Date.now());
    return {
        id: "long-turn-watchdog",
        priority: 278,
        async event(type, payload) {
            if (!options.enabled) {
                return;
            }
            if (type === "session.deleted") {
                const sessionId = resolveSessionId((payload ?? {}));
                if (sessionId) {
                    states.delete(sessionId);
                }
                return;
            }
            if (type === "chat.message") {
                const eventPayload = (payload ?? {});
                const sessionId = resolveSessionId(eventPayload);
                if (!sessionId) {
                    return;
                }
                const ts = now();
                const previous = states.get(sessionId);
                states.set(sessionId, {
                    turnStartMs: ts,
                    turnCounter: (previous?.turnCounter ?? 0) + 1,
                    warnedTurnCounter: previous?.warnedTurnCounter ?? 0,
                    lastWarnedAtMs: previous?.lastWarnedAtMs ?? 0,
                    lastSeenAtMs: ts,
                });
                pruneStates(states, options.maxSessionStateEntries);
                return;
            }
            if (type !== "tool.execute.after") {
                return;
            }
            const eventPayload = (payload ?? {});
            const directory = typeof eventPayload.directory === "string" && eventPayload.directory.trim()
                ? eventPayload.directory
                : options.directory;
            const sessionId = resolveSessionId(eventPayload);
            if (!sessionId) {
                writeGatewayEventAudit(directory, {
                    hook: "long-turn-watchdog",
                    stage: "skip",
                    reason_code: "missing_session_id",
                });
                return;
            }
            const state = states.get(sessionId);
            if (!state) {
                writeGatewayEventAudit(directory, {
                    hook: "long-turn-watchdog",
                    stage: "skip",
                    reason_code: "missing_turn_start",
                    session_id: sessionId,
                });
                return;
            }
            state.lastSeenAtMs = now();
            if (typeof eventPayload.output?.output !== "string") {
                writeGatewayEventAudit(directory, {
                    hook: "long-turn-watchdog",
                    stage: "skip",
                    reason_code: "output_not_text",
                    session_id: sessionId,
                });
                return;
            }
            const elapsedMs = Math.max(0, now() - state.turnStartMs);
            if (elapsedMs < options.warningThresholdMs) {
                writeGatewayEventAudit(directory, {
                    hook: "long-turn-watchdog",
                    stage: "skip",
                    reason_code: "below_threshold",
                    session_id: sessionId,
                    elapsed_ms: elapsedMs,
                    warning_threshold_ms: options.warningThresholdMs,
                });
                return;
            }
            const sameTurnWarned = state.warnedTurnCounter === state.turnCounter;
            if (sameTurnWarned) {
                writeGatewayEventAudit(directory, {
                    hook: "long-turn-watchdog",
                    stage: "skip",
                    reason_code: "already_warned_for_turn",
                    session_id: sessionId,
                    elapsed_ms: elapsedMs,
                    turn_counter: state.turnCounter,
                });
                return;
            }
            if (options.reminderCooldownMs > 0 &&
                state.lastWarnedAtMs > 0 &&
                now() - state.lastWarnedAtMs < options.reminderCooldownMs) {
                writeGatewayEventAudit(directory, {
                    hook: "long-turn-watchdog",
                    stage: "skip",
                    reason_code: "cooldown_active",
                    session_id: sessionId,
                    elapsed_ms: elapsedMs,
                    reminder_cooldown_ms: options.reminderCooldownMs,
                });
                return;
            }
            const prefix = options.prefix.trim() || "[Turn Watchdog]:";
            const warning = `${prefix} Long turn detected (${formatDuration(elapsedMs)} since last user message; threshold ${formatDuration(options.warningThresholdMs)}).`;
            eventPayload.output.output = `${eventPayload.output.output}\n\n${warning}`;
            state.warnedTurnCounter = state.turnCounter;
            state.lastWarnedAtMs = now();
            writeGatewayEventAudit(directory, {
                hook: "long-turn-watchdog",
                stage: "state",
                reason_code: "long_turn_warning",
                session_id: sessionId,
                elapsed_ms: elapsedMs,
                warning_threshold_ms: options.warningThresholdMs,
                turn_started_at: new Date(state.turnStartMs).toISOString(),
            });
        },
    };
}

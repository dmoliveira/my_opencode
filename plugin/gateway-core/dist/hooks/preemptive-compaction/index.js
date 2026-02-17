import { writeGatewayEventAudit } from "../../audit/event-audit.js";
import { resolveContextLimit } from "../shared/context-limit.js";
const CONTEXT_GUARD_PREFIX = "󰚩 Context Guard:";
function guardPrefix(mode) {
    if (mode === "plain") {
        return "[Context Guard]:";
    }
    if (mode === "both") {
        return "󰚩 Context Guard [Context Guard]:";
    }
    return CONTEXT_GUARD_PREFIX;
}
function pruneSessionStates(states, maxEntries) {
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
// Resolves effective session id across payload variants.
function resolveSessionId(payload) {
    const candidates = [payload.input?.sessionID, payload.input?.sessionId];
    for (const value of candidates) {
        if (typeof value === "string" && value.trim()) {
            return value.trim();
        }
    }
    return "";
}
// Creates preemptive compaction hook for high context pressure sessions.
export function createPreemptiveCompactionHook(options) {
    const compactionInProgress = new Set();
    const sessionStates = new Map();
    return {
        id: "preemptive-compaction",
        priority: 270,
        async event(type, payload) {
            if (!options.enabled) {
                return;
            }
            if (type === "session.deleted") {
                const eventPayload = (payload ?? {});
                const sessionId = eventPayload.properties?.info?.id;
                if (typeof sessionId === "string" && sessionId.trim()) {
                    const resolvedSessionId = sessionId.trim();
                    compactionInProgress.delete(resolvedSessionId);
                    sessionStates.delete(resolvedSessionId);
                }
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
                return;
            }
            const priorState = sessionStates.get(sessionId) ?? {
                toolCalls: 0,
                lastCompactedAtToolCall: 0,
                lastCompactedTokens: 0,
                lastMissingMetadataNoticeAtToolCall: 0,
                lastSeenAtMs: Date.now(),
            };
            const nextState = {
                ...priorState,
                toolCalls: priorState.toolCalls + 1,
                lastSeenAtMs: Date.now(),
            };
            sessionStates.set(sessionId, nextState);
            pruneSessionStates(sessionStates, options.maxSessionStateEntries);
            if (compactionInProgress.has(sessionId)) {
                return;
            }
            const client = options.client?.session;
            if (!client) {
                return;
            }
            try {
                const response = await client.messages({ path: { id: sessionId }, query: { directory } });
                const messages = Array.isArray(response.data) ? response.data : [];
                const assistants = messages
                    .filter((item) => item.info?.role === "assistant")
                    .map((item) => item.info);
                const last = assistants[assistants.length - 1];
                if (!last) {
                    return;
                }
                const providerID = typeof last.providerID === "string" ? last.providerID : "";
                const modelID = typeof last.modelID === "string" ? last.modelID : "";
                const actualLimit = resolveContextLimit({
                    providerID,
                    modelID,
                    defaultContextLimitTokens: options.defaultContextLimitTokens,
                });
                const totalInputTokens = (last.tokens?.input ?? 0) + (last.tokens?.cache?.read ?? 0);
                const usageRatio = totalInputTokens / actualLimit;
                if (usageRatio < options.warningThreshold) {
                    return;
                }
                const hasPriorCompaction = nextState.lastCompactedAtToolCall > 0;
                if (hasPriorCompaction) {
                    const cooldownElapsed = nextState.toolCalls - nextState.lastCompactedAtToolCall >= options.compactionCooldownToolCalls;
                    const tokenDeltaEnough = totalInputTokens - nextState.lastCompactedTokens >= options.minTokenDeltaForCompaction;
                    if (!cooldownElapsed) {
                        writeGatewayEventAudit(directory, {
                            hook: "preemptive-compaction",
                            stage: "skip",
                            reason_code: "compaction_cooldown_not_elapsed",
                            session_id: sessionId,
                        });
                        return;
                    }
                    if (!tokenDeltaEnough) {
                        writeGatewayEventAudit(directory, {
                            hook: "preemptive-compaction",
                            stage: "skip",
                            reason_code: "compaction_token_delta_too_small",
                            session_id: sessionId,
                        });
                        return;
                    }
                }
                if (!providerID || !modelID) {
                    const missingNoticeElapsed = nextState.toolCalls - nextState.lastMissingMetadataNoticeAtToolCall >=
                        options.compactionCooldownToolCalls;
                    if (missingNoticeElapsed && typeof eventPayload.output?.output === "string") {
                        const prefix = guardPrefix(options.guardMarkerMode);
                        eventPayload.output.output = `${eventPayload.output.output}\n\n${prefix} High context pressure detected but auto-compaction skipped: provider/model metadata unavailable.`;
                        sessionStates.set(sessionId, {
                            ...nextState,
                            lastMissingMetadataNoticeAtToolCall: nextState.toolCalls,
                        });
                    }
                    writeGatewayEventAudit(directory, {
                        hook: "preemptive-compaction",
                        stage: "skip",
                        reason_code: "compaction_missing_provider_or_model",
                        session_id: sessionId,
                    });
                    return;
                }
                compactionInProgress.add(sessionId);
                await client.summarize({
                    path: { id: sessionId },
                    body: { providerID, modelID, auto: true },
                    query: { directory },
                });
                if (typeof eventPayload.output?.output === "string") {
                    const prefix = guardPrefix(options.guardMarkerMode);
                    if (options.guardVerbosity === "minimal") {
                        eventPayload.output.output = `${eventPayload.output.output}\n\n${prefix} Preemptive compaction triggered.`;
                    }
                    else if (options.guardVerbosity === "debug") {
                        eventPayload.output.output = `${eventPayload.output.output}\n\n${prefix} Preemptive compaction triggered to reduce context pressure.\n[threshold ${(options.warningThreshold * 100).toFixed(1)}%, cooldown=${options.compactionCooldownToolCalls} calls, min_delta=${options.minTokenDeltaForCompaction} tokens]`;
                    }
                    else {
                        eventPayload.output.output = `${eventPayload.output.output}\n\n${prefix} Preemptive compaction triggered to reduce context pressure.`;
                    }
                }
                sessionStates.set(sessionId, {
                    ...nextState,
                    lastCompactedAtToolCall: nextState.toolCalls,
                    lastCompactedTokens: totalInputTokens,
                });
                writeGatewayEventAudit(directory, {
                    hook: "preemptive-compaction",
                    stage: "state",
                    reason_code: "session_compacted_preemptively",
                    session_id: sessionId,
                });
            }
            catch {
                writeGatewayEventAudit(directory, {
                    hook: "preemptive-compaction",
                    stage: "skip",
                    reason_code: "session_compaction_failed",
                    session_id: sessionId,
                });
            }
            finally {
                compactionInProgress.delete(sessionId);
            }
        },
    };
}

import { writeGatewayEventAudit } from "../../audit/event-audit.js";
import { injectHookMessage } from "../hook-message-injector/index.js";
import { truncateInjectedText } from "../shared/injected-text-truncator.js";
const CONTINUE_LOOP_MARKER = "<CONTINUE-LOOP>";
function resolveSessionId(payload) {
    const candidates = [
        payload.properties?.sessionID,
        payload.properties?.sessionId,
        payload.properties?.info?.id,
        payload.input?.sessionID,
        payload.input?.sessionId,
    ];
    for (const value of candidates) {
        if (typeof value === "string" && value.trim()) {
            return value.trim();
        }
    }
    return "";
}
function resolveDirectory(payload, fallback) {
    return typeof payload.directory === "string" && payload.directory.trim() ? payload.directory : fallback;
}
function buildRestoreMessage(snapshotText) {
    return [
        "[COMPACTION TODO CONTEXT]",
        "Session compaction was detected. Restore and continue pending todo work from this snapshot:",
        snapshotText,
        "Continue execution without asking for extra confirmation until pending tasks are complete.",
    ].join("\n\n");
}
export function createCompactionTodoPreserverHook(options) {
    const snapshotBySession = new Map();
    return {
        id: "compaction-todo-preserver",
        priority: 346,
        async event(type, payload) {
            if (!options.enabled) {
                return;
            }
            if (type === "session.deleted") {
                const eventPayload = (payload ?? {});
                const sessionId = resolveSessionId(eventPayload);
                if (sessionId) {
                    snapshotBySession.delete(sessionId);
                }
                return;
            }
            if (type === "tool.execute.after") {
                const eventPayload = (payload ?? {});
                const sessionId = resolveSessionId(eventPayload);
                const tool = String(eventPayload.input?.tool ?? "").toLowerCase();
                if (!sessionId || tool !== "task" || typeof eventPayload.output?.output !== "string") {
                    return;
                }
                const raw = eventPayload.output.output;
                if (!raw.includes(CONTINUE_LOOP_MARKER)) {
                    snapshotBySession.delete(sessionId);
                    return;
                }
                const truncated = truncateInjectedText(raw, options.maxChars);
                if (!truncated.text.trim()) {
                    return;
                }
                snapshotBySession.set(sessionId, {
                    text: truncated.text,
                    pendingRestore: true,
                });
                return;
            }
            if (type !== "session.compacted") {
                return;
            }
            const eventPayload = (payload ?? {});
            const directory = resolveDirectory(eventPayload, options.directory);
            const sessionId = resolveSessionId(eventPayload);
            if (!sessionId) {
                return;
            }
            const state = snapshotBySession.get(sessionId);
            if (!state?.pendingRestore) {
                writeGatewayEventAudit(directory, {
                    hook: "compaction-todo-preserver",
                    stage: "skip",
                    reason_code: "compaction_todo_no_snapshot",
                    session_id: sessionId,
                });
                return;
            }
            const client = options.client?.session;
            if (!client) {
                return;
            }
            const restored = await injectHookMessage({
                session: client,
                sessionId,
                content: buildRestoreMessage(state.text),
                directory,
            });
            if (!restored) {
                writeGatewayEventAudit(directory, {
                    hook: "compaction-todo-preserver",
                    stage: "inject",
                    reason_code: "compaction_todo_restore_failed",
                    session_id: sessionId,
                });
                return;
            }
            state.pendingRestore = false;
            snapshotBySession.set(sessionId, state);
            writeGatewayEventAudit(directory, {
                hook: "compaction-todo-preserver",
                stage: "inject",
                reason_code: "compaction_todo_restored",
                session_id: sessionId,
            });
        },
    };
}

import { writeGatewayEventAudit } from "../../audit/event-audit.js";
import { injectHookMessage, inspectHookMessageSafety } from "../hook-message-injector/index.js";
import { readCombinedToolAfterOutputText } from "../shared/tool-after-output.js";
function isRecoverableError(error) {
    const candidate = error && typeof error === "object" && "message" in error
        ? String(error.message ?? "")
        : String(error ?? "");
    const message = candidate.toLowerCase();
    return (message.includes("context") ||
        message.includes("rate limit") ||
        message.includes("temporar") ||
        message.includes("network") ||
        message.includes("timeout"));
}
function resolveSessionId(payload) {
    const candidates = [payload.properties?.sessionID, payload.properties?.sessionId, payload.properties?.info?.id];
    for (const value of candidates) {
        if (typeof value === "string" && value.trim()) {
            return value.trim();
        }
    }
    return "";
}
function looksLikeDelegatedTaskAbort(output) {
    const text = readCombinedToolAfterOutputText(output);
    const record = output && typeof output === "object" ? output : null;
    const nested = record && record.output && typeof record.output === "object"
        ? record.output
        : record;
    const state = nested?.state && typeof nested.state === "object" ? nested.state : null;
    const metadata = state?.metadata && typeof state.metadata === "object" ? state.metadata : null;
    const status = String(state?.status ?? "").trim().toLowerCase();
    const error = `${String(state?.error ?? "")}
${String(nested?.error ?? "")}
${text}`.toLowerCase();
    const childSessionId = String(metadata?.sessionId ?? metadata?.sessionID ?? "").trim();
    return {
        aborted: status === "error" && error.includes("tool execution aborted"),
        childSessionId,
    };
}
async function injectRecoveryMessage(args) {
    const safety = await inspectHookMessageSafety({
        session: args.session,
        sessionId: args.sessionId,
        directory: args.directory,
    });
    if (!safety.safe) {
        writeGatewayEventAudit(args.directory, {
            hook: args.hook,
            stage: "skip",
            reason_code: `${args.reasonCode}_${safety.reason}`,
            session_id: args.sessionId,
        });
        return false;
    }
    const injected = await injectHookMessage({
        session: args.session,
        sessionId: args.sessionId,
        content: args.content,
        directory: args.directory,
    });
    if (!injected) {
        writeGatewayEventAudit(args.directory, {
            hook: args.hook,
            stage: "skip",
            reason_code: `${args.reasonCode}_inject_failed`,
            session_id: args.sessionId,
        });
        return false;
    }
    writeGatewayEventAudit(args.directory, {
        hook: args.hook,
        stage: "state",
        reason_code: `${args.reasonCode}_injected`,
        session_id: args.sessionId,
    });
    return true;
}
export function createSessionRecoveryHook(options) {
    const recoveringSessions = new Set();
    return {
        id: "session-recovery",
        priority: 280,
        async event(type, payload) {
            if (!options.enabled) {
                return;
            }
            const eventPayload = (payload ?? {});
            if (type === "session.deleted") {
                const sessionId = resolveSessionId(eventPayload);
                if (sessionId) {
                    recoveringSessions.delete(sessionId);
                }
                return;
            }
            if (type === "tool.execute.after") {
                const toolPayload = (payload ?? {});
                const sessionId = String(toolPayload.input?.sessionID ?? toolPayload.input?.sessionId ?? "").trim();
                const directory = typeof toolPayload.directory === "string" && toolPayload.directory.trim()
                    ? toolPayload.directory
                    : options.directory;
                if (!sessionId || String(toolPayload.input?.tool ?? "").trim().toLowerCase() !== "task") {
                    return;
                }
                if (recoveringSessions.has(sessionId)) {
                    return;
                }
                const client = options.client?.session;
                if (!client || !options.autoResume) {
                    return;
                }
                const delegatedAbort = looksLikeDelegatedTaskAbort(toolPayload.output?.output);
                if (!delegatedAbort.aborted) {
                    return;
                }
                recoveringSessions.add(sessionId);
                try {
                    await injectRecoveryMessage({
                        session: client,
                        sessionId,
                        directory,
                        hook: "session-recovery",
                        reasonCode: "delegated_task_abort_recovery",
                        content: delegatedAbort.childSessionId
                            ? `[delegated task aborted - continuing in parent turn]\nchild_session: ${delegatedAbort.childSessionId}`
                            : "[delegated task aborted - continuing in parent turn]",
                    });
                }
                catch {
                    writeGatewayEventAudit(directory, {
                        hook: "session-recovery",
                        stage: "skip",
                        reason_code: "delegated_task_abort_recovery_failed",
                        session_id: sessionId,
                    });
                }
                finally {
                    recoveringSessions.delete(sessionId);
                }
                return;
            }
            if (type !== "session.error") {
                return;
            }
            const directory = typeof eventPayload.directory === "string" && eventPayload.directory.trim()
                ? eventPayload.directory
                : options.directory;
            const sessionId = resolveSessionId(eventPayload);
            if (!sessionId) {
                writeGatewayEventAudit(directory, {
                    hook: "session-recovery",
                    stage: "skip",
                    reason_code: "missing_session_id",
                });
                return;
            }
            if (recoveringSessions.has(sessionId)) {
                writeGatewayEventAudit(directory, {
                    hook: "session-recovery",
                    stage: "skip",
                    reason_code: "recovery_in_progress",
                    session_id: sessionId,
                });
                return;
            }
            const error = eventPayload.properties?.error ?? eventPayload.properties?.info?.error;
            if (!isRecoverableError(error)) {
                writeGatewayEventAudit(directory, {
                    hook: "session-recovery",
                    stage: "skip",
                    reason_code: "error_not_recoverable",
                    session_id: sessionId,
                });
                return;
            }
            if (!options.autoResume) {
                writeGatewayEventAudit(directory, {
                    hook: "session-recovery",
                    stage: "skip",
                    reason_code: "auto_resume_disabled",
                    session_id: sessionId,
                });
                return;
            }
            const client = options.client?.session;
            if (!client) {
                writeGatewayEventAudit(directory, {
                    hook: "session-recovery",
                    stage: "skip",
                    reason_code: "session_client_unavailable",
                    session_id: sessionId,
                });
                return;
            }
            recoveringSessions.add(sessionId);
            try {
                await injectRecoveryMessage({
                    session: client,
                    sessionId,
                    directory,
                    hook: "session-recovery",
                    reasonCode: "session_recovery_resume",
                    content: "[session recovered - continuing previous task]",
                });
            }
            catch {
                writeGatewayEventAudit(directory, {
                    hook: "session-recovery",
                    stage: "skip",
                    reason_code: "session_recovery_resume_failed",
                    session_id: sessionId,
                });
            }
            finally {
                recoveringSessions.delete(sessionId);
            }
        },
    };
}

import { writeGatewayEventAudit } from "../../audit/event-audit.js";
import { nowIso, transactGatewayStateDomain } from "../../state/storage.js";
import { isGitHubPrCreateCommand, isGitHubPrMergeCommand } from "../shared/github-pr-commands.js";
import { classifyValidationCommand } from "../shared/validation-command-matcher.js";
const CONTROL_CHARACTER = /[\u0000-\u001f\u007f]/;
const CONTROL_CHARACTERS = /[\u0000-\u001f\u007f]/g;
function isRecord(value) {
    return Boolean(value && typeof value === "object" && !Array.isArray(value));
}
function setOwn(target, key, value) {
    Object.defineProperty(target, key, {
        value,
        enumerable: true,
        configurable: true,
        writable: true,
    });
}
function sessionId(payload) {
    const value = payload.input?.sessionID ??
        payload.input?.sessionId ??
        payload.properties?.info?.id ??
        "";
    return typeof value === "string" ? value.trim() : "";
}
function command(payload) {
    const value = payload.input?.args?.command ?? payload.output?.args?.command ?? "";
    return typeof value === "string" ? value.trim() : "";
}
function tool(payload) {
    return String(payload.input?.tool ?? "").trim().toLowerCase();
}
function exitCode(payload) {
    const metadata = payload.output?.metadata;
    if (!isRecord(metadata) || typeof metadata.exit !== "number" || !Number.isFinite(metadata.exit)) {
        return null;
    }
    return metadata.exit;
}
function label(value, maxChars) {
    const compact = value.replace(CONTROL_CHARACTERS, " ").replace(/\s+/g, " ").trim();
    if (compact.length <= maxChars) {
        return compact;
    }
    return `${compact.slice(0, Math.max(1, maxChars - 1)).trimEnd()}…`;
}
function stageFor(payload) {
    const name = tool(payload);
    if (["edit", "write", "apply_patch"].includes(name)) {
        return {
            running: "Update files",
            passed: "Files updated",
            completed: "Files updated",
            next: "Run validation",
            failed: "File update failed",
            failedNext: "Resolve file update",
        };
    }
    if (name === "task") {
        return {
            running: "Run delegated work",
            passed: "Delegated work returned",
            completed: "Delegated work returned",
            next: "Continue execution",
            failed: "Delegated work failed",
            failedNext: "Resolve delegated work",
        };
    }
    if (name !== "bash") {
        return null;
    }
    const value = command(payload);
    if (!value) {
        return null;
    }
    if (classifyValidationCommand(value).length > 0) {
        return {
            running: "Run validation",
            passed: "Validation passed",
            completed: "Validation completed",
            next: "Review changes",
            failed: "Validation failed",
            failedNext: "Fix validation",
        };
    }
    if (isGitHubPrMergeCommand(value)) {
        return {
            running: "Merge pull request",
            passed: "Pull request merged",
            completed: "Merge completed",
            next: "Sync main",
            failed: "Pull request merge failed",
            failedNext: "Resolve merge",
        };
    }
    if (isGitHubPrCreateCommand(value)) {
        return {
            running: "Open pull request",
            passed: "Pull request opened",
            completed: "Pull request creation completed",
            next: "Review pull request",
            failed: "Pull request creation failed",
            failedNext: "Resolve pull request",
        };
    }
    if (/^(?:env\s+)?(?:[A-Za-z_][A-Za-z0-9_]*=(?:"[^"]*"|'[^']*'|\S+)\s+)*git\s+commit\b/i.test(value)) {
        return {
            running: "Commit changes",
            passed: "Changes committed",
            completed: "Commit completed",
            next: "Push branch",
            failed: "Commit failed",
            failedNext: "Resolve commit",
        };
    }
    if (/^(?:env\s+)?(?:[A-Za-z_][A-Za-z0-9_]*=(?:"[^"]*"|'[^']*'|\S+)\s+)*git\s+push\b/i.test(value)) {
        return {
            running: "Push branch",
            passed: "Branch pushed",
            completed: "Push completed",
            next: "Open pull request",
            failed: "Push failed",
            failedNext: "Resolve push",
        };
    }
    return null;
}
function parseStatus(value) {
    const sessions = Object.create(null);
    if (!isRecord(value) || value.version !== 1 || !isRecord(value.sessions)) {
        return { version: 1, sessions };
    }
    for (const [id, entry] of Object.entries(value.sessions)) {
        if (!id ||
            id.length > 160 ||
            CONTROL_CHARACTER.test(id) ||
            !isRecord(entry) ||
            entry.sessionId !== id ||
            typeof entry.last !== "string" ||
            typeof entry.next !== "string" ||
            typeof entry.updatedAt !== "string") {
            continue;
        }
        setOwn(sessions, id, {
            sessionId: id,
            last: entry.last,
            next: entry.next,
            updatedAt: entry.updatedAt,
        });
    }
    return { version: 1, sessions };
}
function boundedSessions(sessions, maxSessions, protectedSessionId) {
    const entries = Object.entries(sessions).sort((left, right) => left[1].updatedAt.localeCompare(right[1].updatedAt));
    const retained = Object.create(null);
    const keep = new Set(entries
        .slice(Math.max(0, entries.length - maxSessions))
        .map(([sessionId]) => sessionId));
    keep.add(protectedSessionId);
    for (const [id, entry] of entries) {
        if (keep.has(id)) {
            setOwn(retained, id, entry);
        }
    }
    return retained;
}
function sameEntry(left, right) {
    return Boolean(left && left.last === right.last && left.next === right.next);
}
// Maintains a small, deterministic, per-session status ledger without prompts or model calls.
export function createExecutionStatusHook(options) {
    const update = (id, change, reason) => {
        if (!id) {
            return;
        }
        try {
            const result = transactGatewayStateDomain(options.directory, "executionStatus", (current) => {
                const status = parseStatus(current);
                const existing = status.sessions[id];
                const next = {
                    sessionId: id,
                    last: label(change.last ?? existing?.last ?? "Session ready", options.maxLabelChars),
                    next: label(change.next ?? existing?.next ?? "Begin execution", options.maxLabelChars),
                    updatedAt: nowIso(),
                };
                if (sameEntry(existing, next)) {
                    return null;
                }
                const sessions = Object.create(null);
                for (const [sessionId, entry] of Object.entries(status.sessions)) {
                    setOwn(sessions, sessionId, entry);
                }
                setOwn(sessions, id, next);
                return {
                    value: {
                        version: 1,
                        sessions: boundedSessions(sessions, options.maxSessions, id),
                    },
                    mode: "replace",
                    rootUpdates: { lastUpdatedAt: next.updatedAt, source: "execution-status" },
                };
            });
            if (result.changed) {
                writeGatewayEventAudit(options.directory, {
                    hook: "execution-status",
                    stage: "state",
                    reason_code: reason,
                    session_id: id,
                });
            }
        }
        catch {
            writeGatewayEventAudit(options.directory, {
                hook: "execution-status",
                stage: "skip",
                reason_code: "execution_status_state_unavailable",
                session_id: id,
            });
        }
    };
    const remove = (id) => {
        if (!id) {
            return;
        }
        try {
            transactGatewayStateDomain(options.directory, "executionStatus", (current) => {
                const status = parseStatus(current);
                if (!status.sessions[id]) {
                    return null;
                }
                const sessions = Object.create(null);
                for (const [sessionId, entry] of Object.entries(status.sessions)) {
                    if (sessionId !== id) {
                        setOwn(sessions, sessionId, entry);
                    }
                }
                return {
                    value: { version: 1, sessions },
                    mode: "replace",
                    rootUpdates: { lastUpdatedAt: nowIso(), source: "execution-status" },
                };
            });
        }
        catch {
            // Session cleanup is best-effort and must never affect the active turn.
        }
    };
    return {
        id: "execution-status",
        priority: 335,
        events: [
            "session.created",
            "session.updated",
            "session.deleted",
            "tool.execute.before",
            "tool.execute.after",
            "tool.execute.before.error",
        ],
        async event(type, payload) {
            if (!options.enabled) {
                return;
            }
            const eventPayload = (payload ?? {});
            const id = sessionId(eventPayload);
            if (!id) {
                return;
            }
            if (type === "session.deleted") {
                remove(id);
                return;
            }
            if (type === "session.created" || type === "session.updated") {
                update(id, {}, "execution_status_session_ready");
                return;
            }
            const stage = stageFor(eventPayload);
            if (!stage) {
                return;
            }
            if (type === "tool.execute.before") {
                update(id, { next: stage.running }, "execution_status_action_started");
                return;
            }
            const code = exitCode(eventPayload);
            const failed = type === "tool.execute.before.error" || (code !== null && code !== 0);
            update(id, failed
                ? { last: stage.failed, next: stage.failedNext }
                : { last: code === null ? stage.completed : stage.passed, next: stage.next }, failed ? "execution_status_action_failed" : "execution_status_action_completed");
        },
    };
}

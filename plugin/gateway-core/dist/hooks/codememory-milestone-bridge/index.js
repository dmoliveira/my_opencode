import { createHash } from "node:crypto";
import { spawn } from "node:child_process";
import { writeGatewayEventAudit } from "../../audit/event-audit.js";
import { isGitHubPrCreateCommand, isGitHubPrMergeCommand } from "../shared/github-pr-commands.js";
import { readToolAfterOutputText } from "../shared/tool-after-output.js";
import { classifyValidationCommand } from "../shared/validation-command-matcher.js";
const ACTOR = "gateway-core:codememory-milestone-bridge";
const TERMINATION_GRACE_MS = 250;
const FAILURE_OUTPUT = /(^\s*\[error\]|^\s*error:|^\s*exception:|^\s*traceback\b|^\s*invalid arguments\b|^\s*unknown\s+agent\b|^\s*unknown\s+category\b|^\s*blocked delegation\b)/im;
function normalize(value) {
    return String(value ?? "")
        .replace(/\s+/g, " ")
        .trim();
}
function sessionId(payload) {
    return normalize(payload.input?.sessionID ??
        payload.input?.sessionId ??
        payload.properties?.info?.id);
}
function callId(payload) {
    return normalize(payload.input?.callID ?? payload.input?.callId);
}
function directoryFor(payload, fallback) {
    return typeof payload.directory === "string" && payload.directory.trim()
        ? payload.directory
        : fallback;
}
function toolName(payload) {
    return normalize(payload.input?.tool).toLowerCase();
}
function commandFromPayload(payload) {
    return normalize(payload.input?.args?.command ?? payload.output?.args?.command);
}
function exitCode(payload) {
    const metadata = payload.output?.metadata;
    if (!metadata || typeof metadata !== "object") {
        return null;
    }
    const exit = metadata.exit;
    return typeof exit === "number" && Number.isFinite(exit) ? exit : null;
}
function failureFromTaskOutput(payload) {
    const output = readToolAfterOutputText(payload.output?.output);
    if (!output.trim()) {
        return null;
    }
    return FAILURE_OUTPUT.test(output);
}
function fingerprint(value) {
    return createHash("sha256").update(value).digest("hex").slice(0, 20);
}
function requestId(milestone) {
    return `cm_bridge_${fingerprint([
        milestone.directory,
        milestone.sessionId,
        milestone.kind,
        milestone.outcome,
        milestone.identity,
        ...milestone.details,
    ].join("\u0000"))}`;
}
function milestoneText(milestone) {
    const fields = [
        `milestone=${milestone.kind}`,
        `outcome=${milestone.outcome}`,
        `session=${milestone.sessionId}`,
        ...milestone.details,
    ];
    return fields.join(" ");
}
function terminateChild(child, signal) {
    if (process.platform !== "win32" && typeof child.pid === "number" && child.pid > 0) {
        try {
            process.kill(-child.pid, signal);
            return;
        }
        catch {
            // Fall back to the direct child when a process group is unavailable.
        }
    }
    try {
        child.kill(signal);
    }
    catch {
        // The child may already have exited.
    }
}
function classifyMilestone(type, payload, fallbackDirectory) {
    const tool = toolName(payload);
    if (!tool || (type !== "tool.execute.after" && type !== "tool.execute.before.error")) {
        return null;
    }
    const sid = sessionId(payload);
    if (!sid) {
        return null;
    }
    const directory = directoryFor(payload, fallbackDirectory);
    const command = commandFromPayload(payload);
    const invocation = callId(payload);
    if (tool === "task") {
        const subagentType = normalize(payload.output?.args?.subagent_type).toLowerCase();
        const category = normalize(payload.output?.args?.category).toLowerCase();
        const trace = normalize(payload.output?.metadata && typeof payload.output.metadata === "object"
            ? payload.output.metadata.trace_id ??
                payload.output.metadata.traceId
            : "");
        const failed = type === "tool.execute.before.error" ? true : failureFromTaskOutput(payload);
        if (failed === null) {
            return null;
        }
        const identity = invocation || trace || `${subagentType}:${category}`;
        if (!identity) {
            return null;
        }
        return {
            kind: "delegation",
            outcome: failed ? "failed" : "passed",
            sessionId: sid,
            identity,
            details: [
                subagentType ? `subagent=${subagentType}` : "subagent=unknown",
                category ? `category=${category}` : "category=unknown",
                trace ? `trace=${trace}` : "",
            ].filter(Boolean),
            directory,
        };
    }
    if (tool !== "bash" || !command) {
        return null;
    }
    const failed = type === "tool.execute.before.error" ? true : exitCode(payload) !== 0;
    if (type === "tool.execute.after" && exitCode(payload) === null) {
        return null;
    }
    const categories = classifyValidationCommand(command);
    if (categories.length > 0) {
        return {
            kind: "validation",
            outcome: failed ? "failed" : "passed",
            sessionId: sid,
            identity: invocation || fingerprint(command),
            details: [
                `categories=${categories.join(",")}`,
                `command_hash=${fingerprint(command)}`,
            ],
            directory,
        };
    }
    if (isGitHubPrCreateCommand(command)) {
        return {
            kind: "pr_create",
            outcome: failed ? "failed" : "passed",
            sessionId: sid,
            identity: invocation || fingerprint(command),
            details: [`command_hash=${fingerprint(command)}`],
            directory,
        };
    }
    if (isGitHubPrMergeCommand(command)) {
        return {
            kind: "pr_merge",
            outcome: failed ? "failed" : "passed",
            sessionId: sid,
            identity: invocation || fingerprint(command),
            details: [`command_hash=${fingerprint(command)}`],
            directory,
        };
    }
    return null;
}
// Creates an opt-in, fail-open bridge for durable Codememory milestone notes.
export function createCodememoryMilestoneBridgeHook(options) {
    const spawnProcess = options.spawnProcess ?? spawn;
    const pending = new Map();
    let activeRequestId = "";
    let draining = false;
    function audit(reasonCode, item) {
        writeGatewayEventAudit(item.directory || options.directory, {
            hook: "codememory-milestone-bridge",
            stage: reasonCode === "codememory_event_sent" ? "state" : "skip",
            reason_code: reasonCode,
            session_id: item.sessionId,
            request_id: item.requestId,
            milestone: item.kind,
            outcome: item.outcome,
        });
    }
    function send(item) {
        return new Promise((resolve) => {
            let settled = false;
            let timeoutTimer;
            let terminationTimer;
            let timedOut = false;
            const finish = (reasonCode) => {
                if (settled) {
                    return;
                }
                settled = true;
                if (timeoutTimer) {
                    clearTimeout(timeoutTimer);
                }
                if (terminationTimer) {
                    clearTimeout(terminationTimer);
                }
                audit(reasonCode, item);
                resolve();
            };
            const args = [
                "event",
                "noted",
                item.text,
                "--format",
                "json",
                "--request-id",
                item.requestId,
                "--actor",
                ACTOR,
            ];
            let child;
            try {
                child = spawnProcess(options.command, args, {
                    cwd: item.directory,
                    detached: process.platform !== "win32",
                    stdio: "ignore",
                });
            }
            catch {
                finish("codememory_spawn_failed");
                return;
            }
            timeoutTimer = setTimeout(() => {
                timedOut = true;
                terminationTimer = setTimeout(() => {
                    terminateChild(child, "SIGKILL");
                    finish("codememory_timeout");
                }, TERMINATION_GRACE_MS);
                terminateChild(child, "SIGTERM");
            }, options.timeoutMs);
            child.once("error", () => finish(timedOut ? "codememory_timeout" : "codememory_process_error"));
            child.once("close", (code) => finish(timedOut
                ? "codememory_timeout"
                : code === 0
                    ? "codememory_event_sent"
                    : "codememory_event_failed"));
        });
    }
    function drain() {
        if (draining) {
            return;
        }
        draining = true;
        void (async () => {
            while (pending.size > 0) {
                const next = pending.entries().next().value;
                if (!next) {
                    break;
                }
                const [id, item] = next;
                pending.delete(id);
                activeRequestId = id;
                await send(item);
                activeRequestId = "";
            }
            draining = false;
        })().catch(() => {
            draining = false;
        });
    }
    function enqueue(milestone) {
        const id = requestId(milestone);
        if (id === activeRequestId || pending.has(id)) {
            audit("codememory_milestone_deduplicated", { ...milestone, requestId: id });
            return;
        }
        if (pending.size >= Math.max(1, options.maxQueueEntries)) {
            audit("codememory_queue_full_dropped", { ...milestone, requestId: id });
            return;
        }
        const item = {
            ...milestone,
            requestId: id,
            text: milestoneText(milestone),
        };
        pending.set(id, item);
        drain();
    }
    return {
        id: "codememory-milestone-bridge",
        priority: 448,
        events: [
            "tool.execute.before",
            "tool.execute.after",
            "tool.execute.before.error",
            "session.deleted",
        ],
        async event(type, payload) {
            if (!options.enabled) {
                return;
            }
            const eventPayload = (payload ?? {});
            if (type === "session.deleted") {
                return;
            }
            const milestone = classifyMilestone(type, eventPayload, options.directory);
            if (milestone) {
                enqueue(milestone);
            }
        },
    };
}

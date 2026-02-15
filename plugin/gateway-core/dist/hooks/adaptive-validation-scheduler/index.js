import { writeGatewayEventAudit } from "../../audit/event-audit.js";
// Resolves stable session id from event payload.
function resolveSessionId(payload) {
    const values = [payload.input?.sessionID, payload.input?.sessionId, payload.properties?.info?.id];
    for (const value of values) {
        if (typeof value === "string" && value.trim()) {
            return value.trim();
        }
    }
    return "";
}
// Returns true when command appears to run validation checks.
function isValidationCommand(command) {
    const value = command.trim().toLowerCase();
    return /\b(npm\s+(run\s+)?(test|lint|build|typecheck)|pnpm\s+(test|lint|build|typecheck)|yarn\s+(test|lint|build|typecheck)|pytest|vitest|jest|ruff\s+check|tsc\b|cargo\s+(test|clippy|check))\b/.test(value);
}
// Returns true when command output looks like failure output.
function commandFailed(output) {
    const value = output.toLowerCase();
    if (/npm err!|exception|traceback|command failed|not found/i.test(value)) {
        return true;
    }
    if (/\bfailed\b/i.test(value) && !/\b(?:0\s+failed|failed\s*:\s*0|failures?\s*:\s*0)\b/i.test(value)) {
        return true;
    }
    return false;
}
// Creates scheduler hook that nudges timely validation after edit bursts.
export function createAdaptiveValidationSchedulerHook(options) {
    const stateBySession = new Map();
    const threshold = options.reminderEditThreshold > 0 ? options.reminderEditThreshold : 3;
    return {
        id: "adaptive-validation-scheduler",
        priority: 334,
        async event(type, payload) {
            if (!options.enabled) {
                return;
            }
            if (type === "session.deleted") {
                const eventPayload = (payload ?? {});
                const sid = resolveSessionId(eventPayload);
                if (sid) {
                    stateBySession.delete(sid);
                }
                return;
            }
            if (type === "tool.execute.before") {
                const eventPayload = (payload ?? {});
                const sid = resolveSessionId(eventPayload);
                if (!sid) {
                    return;
                }
                const current = stateBySession.get(sid) ?? {
                    editsSinceValidation: 0,
                    reminded: false,
                    lastCommand: "",
                };
                const tool = String(eventPayload.input?.tool ?? "").toLowerCase();
                if (tool === "write" || tool === "edit" || tool === "apply_patch") {
                    current.editsSinceValidation += 1;
                }
                if (tool === "bash") {
                    current.lastCommand = String(eventPayload.output?.args?.command ?? "").trim();
                }
                stateBySession.set(sid, current);
                return;
            }
            if (type !== "tool.execute.after") {
                return;
            }
            const eventPayload = (payload ?? {});
            if (String(eventPayload.input?.tool ?? "").toLowerCase() !== "bash") {
                return;
            }
            if (typeof eventPayload.output?.output !== "string") {
                return;
            }
            const sid = resolveSessionId(eventPayload);
            if (!sid) {
                return;
            }
            const current = stateBySession.get(sid);
            if (!current) {
                return;
            }
            if (isValidationCommand(current.lastCommand)) {
                if (!commandFailed(eventPayload.output.output)) {
                    current.editsSinceValidation = 0;
                    current.reminded = false;
                }
                stateBySession.set(sid, current);
                return;
            }
            if (current.editsSinceValidation < threshold || current.reminded) {
                return;
            }
            eventPayload.output.output +=
                "\n\n[adaptive-validation-scheduler] Multiple edits detected. Run a fast validation pass now (lint/typecheck/tests) before proceeding further.";
            current.reminded = true;
            stateBySession.set(sid, current);
            const directory = typeof eventPayload.directory === "string" && eventPayload.directory.trim()
                ? eventPayload.directory
                : options.directory;
            writeGatewayEventAudit(directory, {
                hook: "adaptive-validation-scheduler",
                stage: "state",
                reason_code: "validation_reminder_injected",
                session_id: sid,
            });
        },
    };
}

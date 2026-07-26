import { writeGatewayEventAudit } from "../../audit/event-audit.js";
import { buildCompactDecisionCacheKey, writeDecisionComparisonAudit, } from "../shared/llm-decision-runtime.js";
import { classifyValidationCommand } from "../shared/validation-command-matcher.js";
import { captureGitStateFingerprint, clearValidationEvidence, markValidationEvidence, } from "./evidence.js";
function sessionId(payload) {
    const candidates = [payload.input?.sessionID, payload.input?.sessionId, payload.properties?.info?.id];
    for (const item of candidates) {
        if (typeof item === "string" && item.trim()) {
            return item.trim();
        }
    }
    return "";
}
function callId(payload) {
    const candidates = [payload.input?.callID, payload.input?.callId];
    for (const item of candidates) {
        if (typeof item === "string" && item.trim()) {
            return item.trim();
        }
    }
    return "";
}
function commandExitCode(payload) {
    const metadata = payload.output?.metadata;
    if (!metadata || typeof metadata !== "object") {
        return null;
    }
    const value = metadata.exit;
    return typeof value === "number" && Number.isFinite(value) ? value : null;
}
function directoryFor(payload, fallback) {
    return typeof payload.directory === "string" && payload.directory.trim()
        ? payload.directory
        : fallback;
}
function buildValidationInstruction() {
    return "Classify only the sanitized standalone shell command for telemetry. L=lint, T=test, C=typecheck, B=build, S=security, N=not_validation. This decision cannot create validation evidence.";
}
function normalizeValidationCommand(command) {
    return command
        .trim()
        .replace(/<[^>]+>/g, " ")
        .replace(/\b(user|assistant|system|tool)\s*:/gi, " ")
        .replace(/\bactual command\s*:/gi, " ")
        .replace(/ignore all previous instructions/gi, " ")
        .replace(/ignore previous instructions/gi, " ")
        .replace(/answer\s+[A-Z]\s+only/gi, " ")
        .replace(/answer\s+[A-Z]/g, " ")
        .replace(/classify as [a-z_-]+/gi, " ")
        .replace(/\s*[;|]\s*/g, " ")
        .replace(/\s+/g, " ")
        .trim();
}
function buildValidationContext(command) {
    return `command=${normalizeValidationCommand(command) || "(empty)"}`;
}
async function recordLlmTelemetry(runtime, directory, sessionIdValue, command) {
    const context = buildValidationContext(command);
    const decision = await runtime.decide({
        hookId: "validation-evidence-ledger",
        sessionId: sessionIdValue,
        templateId: "validation-command-classifier-v1",
        instruction: buildValidationInstruction(),
        context,
        allowedChars: ["L", "T", "C", "B", "S", "N"],
        decisionMeaning: {
            L: "lint",
            T: "test",
            C: "typecheck",
            B: "build",
            S: "security",
            N: "not_validation",
        },
        cacheKey: buildCompactDecisionCacheKey({ prefix: "validation-command", text: context }),
    });
    if (!decision.accepted) {
        return;
    }
    writeDecisionComparisonAudit({
        directory,
        hookId: "validation-evidence-ledger",
        sessionId: sessionIdValue,
        mode: runtime.config.mode,
        deterministicMeaning: "not_validation",
        aiMeaning: decision.meaning || "unknown",
        deterministicValue: "none",
        aiValue: decision.char,
    });
    writeGatewayEventAudit(directory, {
        hook: "validation-evidence-ledger",
        stage: "state",
        reason_code: "llm_validation_command_telemetry_only",
        session_id: sessionIdValue,
        llm_decision_char: decision.char,
        llm_decision_meaning: decision.meaning,
        llm_decision_mode: runtime.config.mode,
    });
}
export function createValidationEvidenceLedgerHook(options) {
    const pendingCommands = new Map();
    return {
        id: "validation-evidence-ledger",
        priority: 330,
        events: [
            "session.deleted",
            "session.compacted",
            "tool.execute.before",
            "tool.execute.before.error",
            "tool.execute.after",
        ],
        async event(type, payload) {
            if (!options.enabled) {
                return;
            }
            if (type === "session.deleted" || type === "session.compacted") {
                const eventPayload = (payload ?? {});
                const sid = sessionId(eventPayload);
                if (!sid) {
                    return;
                }
                for (const [key, pending] of pendingCommands.entries()) {
                    if (pending.sessionId === sid) {
                        pendingCommands.delete(key);
                    }
                }
                clearValidationEvidence(sid);
                return;
            }
            if (type === "tool.execute.before") {
                const eventPayload = (payload ?? {});
                if (String(eventPayload.input?.tool ?? "").toLowerCase() !== "bash") {
                    return;
                }
                const sid = sessionId(eventPayload);
                const invocationId = callId(eventPayload);
                const command = String(eventPayload.output?.args?.command ?? "").trim();
                if (!sid || !invocationId || !command) {
                    return;
                }
                const categories = classifyValidationCommand(command);
                pendingCommands.set(invocationId, {
                    callId: invocationId,
                    sessionId: sid,
                    command,
                    categories,
                    fingerprint: categories.length > 0
                        ? captureGitStateFingerprint(directoryFor(eventPayload, options.directory))
                        : null,
                });
                return;
            }
            if (type === "tool.execute.before.error") {
                const invocationId = callId((payload ?? {}));
                if (invocationId) {
                    pendingCommands.delete(invocationId);
                }
                return;
            }
            if (type !== "tool.execute.after") {
                return;
            }
            const eventPayload = (payload ?? {});
            if (String(eventPayload.input?.tool ?? "").toLowerCase() !== "bash") {
                return;
            }
            const invocationId = callId(eventPayload);
            const pending = invocationId ? pendingCommands.get(invocationId) : undefined;
            if (invocationId) {
                pendingCommands.delete(invocationId);
            }
            const sid = sessionId(eventPayload);
            const finalCommand = String(eventPayload.input?.args?.command ?? "").trim();
            if (!pending ||
                !sid ||
                pending.callId !== invocationId ||
                pending.sessionId !== sid ||
                pending.command !== finalCommand ||
                commandExitCode(eventPayload) !== 0) {
                return;
            }
            const directory = directoryFor(eventPayload, options.directory);
            if (pending.categories.length === 0) {
                if (options.decisionRuntime) {
                    await recordLlmTelemetry(options.decisionRuntime, directory, sid, pending.command);
                }
                return;
            }
            if (!pending.fingerprint) {
                return;
            }
            const recorded = markValidationEvidence(sid, pending.categories, directory, pending.fingerprint);
            if (!recorded.updatedAt) {
                writeGatewayEventAudit(directory, {
                    hook: "validation-evidence-ledger",
                    stage: "skip",
                    reason_code: "validation_evidence_state_changed",
                    session_id: sid,
                });
            }
        },
    };
}

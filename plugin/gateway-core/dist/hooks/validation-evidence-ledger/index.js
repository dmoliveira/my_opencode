import { writeGatewayEventAudit } from "../../audit/event-audit.js";
import { clearValidationEvidence, markValidationEvidence, } from "./evidence.js";
// Resolves stable session id across gateway payload variants.
function sessionId(payload) {
    const candidates = [payload.input?.sessionID, payload.input?.sessionId, payload.properties?.info?.id];
    for (const item of candidates) {
        if (typeof item === "string" && item.trim()) {
            return item.trim();
        }
    }
    return "";
}
// Returns true when command output indicates failure.
function commandFailed(output) {
    const lower = output.toLowerCase();
    if (/npm err!|command failed|traceback|exception|cannot find|not found|elifecycle|exit code \d+/i.test(lower)) {
        return true;
    }
    if (/\bfailed\b/i.test(lower) && !/\b(?:0\s+failed|failed\s*:\s*0|failures?\s*:\s*0)\b/i.test(lower)) {
        return true;
    }
    return false;
}
// Classifies validation categories represented by shell command.
function classifyValidationCommand(command) {
    const value = command.trim().toLowerCase();
    if (!value) {
        return [];
    }
    const categories = new Set();
    if (/\b(eslint|ruff\s+check|ruff\s+format\s+--check|npm\s+run\s+lint|pnpm\s+lint|yarn\s+lint|biome\s+check|golangci-lint|cargo\s+clippy)\b/i.test(value)) {
        categories.add("lint");
    }
    if (/\b(npm\s+(run\s+)?test|pnpm\s+test|yarn\s+test|bun\s+test|pytest|vitest|jest|go\s+test|cargo\s+test|pre-commit\s+run)\b/i.test(value)) {
        categories.add("test");
    }
    if (/\b(tsc\b|npm\s+run\s+typecheck|pnpm\s+typecheck|yarn\s+typecheck|pyright|mypy|cargo\s+check|go\s+vet)\b/i.test(value)) {
        categories.add("typecheck");
    }
    if (/\b(npm\s+run\s+build|pnpm\s+build|yarn\s+build|vite\s+build|next\s+build|cargo\s+build|go\s+build)\b/i.test(value)) {
        categories.add("build");
    }
    if (/\b(npm\s+audit|pnpm\s+audit|yarn\s+audit|cargo\s+audit|semgrep|codeql|snyk)\b/i.test(value)) {
        categories.add("security");
    }
    return [...categories];
}
// Creates validation evidence ledger hook to track successful validation commands.
export function createValidationEvidenceLedgerHook(options) {
    const commandBySession = new Map();
    return {
        id: "validation-evidence-ledger",
        priority: 330,
        async event(type, payload) {
            if (!options.enabled) {
                return;
            }
            if (type === "session.deleted") {
                const eventPayload = (payload ?? {});
                const sid = sessionId(eventPayload);
                if (!sid) {
                    return;
                }
                commandBySession.delete(sid);
                clearValidationEvidence(sid);
                return;
            }
            if (type === "tool.execute.before") {
                const eventPayload = (payload ?? {});
                const tool = String(eventPayload.input?.tool ?? "").toLowerCase();
                if (tool !== "bash") {
                    return;
                }
                const sid = sessionId(eventPayload);
                if (!sid) {
                    return;
                }
                const command = String(eventPayload.output?.args?.command ?? "").trim();
                if (!command) {
                    commandBySession.delete(sid);
                    return;
                }
                commandBySession.set(sid, command);
                return;
            }
            if (type !== "tool.execute.after") {
                return;
            }
            const eventPayload = (payload ?? {});
            const tool = String(eventPayload.input?.tool ?? "").toLowerCase();
            if (tool !== "bash" || typeof eventPayload.output?.output !== "string") {
                return;
            }
            const sid = sessionId(eventPayload);
            if (!sid) {
                return;
            }
            const command = commandBySession.get(sid) ?? "";
            if (!command) {
                return;
            }
            const categories = classifyValidationCommand(command);
            if (categories.length === 0) {
                return;
            }
            if (commandFailed(eventPayload.output.output)) {
                return;
            }
            markValidationEvidence(sid, categories);
            const directory = typeof eventPayload.directory === "string" && eventPayload.directory.trim()
                ? eventPayload.directory
                : options.directory;
            writeGatewayEventAudit(directory, {
                hook: "validation-evidence-ledger",
                stage: "state",
                reason_code: "validation_evidence_recorded",
                session_id: sid,
                evidence: categories.join(","),
            });
        },
    };
}

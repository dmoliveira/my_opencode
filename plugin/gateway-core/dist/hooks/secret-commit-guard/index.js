import { execFileSync } from "node:child_process";
import { writeGatewayEventAudit } from "../../audit/event-audit.js";
// Returns true when command mutates staged content or creates a commit.
function isCommitFlow(command) {
    return /\bgit\s+add\b/i.test(command) || /\bgit\s+commit\b/i.test(command);
}
// Compiles configured regex pattern and supports optional inline (?i) prefix.
function compilePattern(pattern) {
    const trimmed = pattern.trim();
    if (!trimmed) {
        return null;
    }
    const caseInsensitive = trimmed.startsWith("(?i)");
    const source = caseInsensitive ? trimmed.slice(4) : trimmed;
    if (!source.trim()) {
        return null;
    }
    try {
        return new RegExp(source, caseInsensitive ? "gi" : "g");
    }
    catch {
        return null;
    }
}
// Returns staged added lines for secret scanning.
function stagedAddedLines(directory) {
    const output = execFileSync("git", ["diff", "--cached", "--no-color", "--unified=0"], {
        cwd: directory,
        stdio: ["ignore", "pipe", "ignore"],
    })
        .toString("utf-8")
        .split(/\r?\n/)
        .filter((line) => line.startsWith("+") && !line.startsWith("+++"))
        .map((line) => line.slice(1))
        .join("\n");
    return output;
}
// Creates secret commit guard that blocks commit flow when staged diff includes secrets.
export function createSecretCommitGuardHook(options) {
    const patterns = options.patterns.map(compilePattern).filter((value) => value !== null);
    return {
        id: "secret-commit-guard",
        priority: 396,
        async event(type, payload) {
            if (!options.enabled || type !== "tool.execute.before") {
                return;
            }
            const eventPayload = (payload ?? {});
            if (String(eventPayload.input?.tool ?? "").toLowerCase() !== "bash") {
                return;
            }
            const command = String(eventPayload.output?.args?.command ?? "").trim();
            if (!isCommitFlow(command)) {
                return;
            }
            const directory = typeof eventPayload.directory === "string" && eventPayload.directory.trim()
                ? eventPayload.directory
                : options.directory;
            const sessionId = String(eventPayload.input?.sessionID ?? eventPayload.input?.sessionId ?? "");
            let staged = "";
            try {
                staged = stagedAddedLines(directory);
            }
            catch {
                return;
            }
            if (!staged.trim() || patterns.length === 0) {
                return;
            }
            const hits = patterns.filter((regex) => {
                regex.lastIndex = 0;
                return regex.test(staged);
            }).length;
            if (hits === 0) {
                return;
            }
            writeGatewayEventAudit(directory, {
                hook: "secret-commit-guard",
                stage: "skip",
                reason_code: "secret_commit_blocked",
                session_id: sessionId,
                matched_pattern_count: hits,
            });
            throw new Error("[secret-commit-guard] Staged diff appears to contain secrets. Remove/redact sensitive data before running git add/commit.");
        },
    };
}

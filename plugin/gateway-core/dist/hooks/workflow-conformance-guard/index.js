import { execSync } from "node:child_process";
import { writeGatewayEventAudit } from "../../audit/event-audit.js";
// Resolves current git branch for workflow branch protection.
function currentBranch(directory) {
    try {
        return execSync("git branch --show-current", { cwd: directory, stdio: ["ignore", "pipe", "ignore"] })
            .toString("utf-8")
            .trim();
    }
    catch {
        return "";
    }
}
// Creates workflow conformance guard for commit operations on protected branches.
export function createWorkflowConformanceGuardHook(options) {
    const protectedSet = new Set(options.protectedBranches.map((item) => item.trim()).filter(Boolean));
    return {
        id: "workflow-conformance-guard",
        priority: 400,
        async event(type, payload) {
            if (!options.enabled || type !== "tool.execute.before") {
                return;
            }
            const eventPayload = (payload ?? {});
            const tool = String(eventPayload.input?.tool ?? "").toLowerCase();
            if (tool !== "bash") {
                return;
            }
            const command = String(eventPayload.output?.args?.command ?? "").trim().toLowerCase();
            if (!command.includes("git commit")) {
                return;
            }
            const directory = typeof eventPayload.directory === "string" && eventPayload.directory.trim()
                ? eventPayload.directory
                : options.directory;
            const branch = currentBranch(directory);
            if (!branch || !protectedSet.has(branch)) {
                return;
            }
            const sessionId = String(eventPayload.input?.sessionID ?? eventPayload.input?.sessionId ?? "");
            writeGatewayEventAudit(directory, {
                hook: "workflow-conformance-guard",
                stage: "skip",
                reason_code: "commit_on_protected_branch_blocked",
                session_id: sessionId,
            });
            throw new Error(`Git commits are blocked on protected branch '${branch}'. Use a worktree feature branch.`);
        },
    };
}

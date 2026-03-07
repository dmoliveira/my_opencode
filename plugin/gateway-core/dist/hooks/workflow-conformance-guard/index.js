import { execSync } from "node:child_process";
import { writeGatewayEventAudit } from "../../audit/event-audit.js";
import { isAllowedProtectedShellCommand } from "../protected-shell-policy.js";
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
const PROTECTED_GIT_MUTATION_PATTERN = /(?:^|&&|\|\||;)\s*(?:env\s+(?:[A-Za-z_][A-Za-z0-9_]*=(?:"[^"]*"|'[^']*'|\S+)\s+)*)?(?:[^\s;&|]*\/)?git\s+(commit|merge|rebase|cherry-pick)\b/i;
function isProtectedGitMutationCommand(command) {
    return PROTECTED_GIT_MUTATION_PATTERN.test(command);
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
            const directory = typeof eventPayload.directory === "string" && eventPayload.directory.trim()
                ? eventPayload.directory
                : options.directory;
            const branch = currentBranch(directory);
            if (!branch || !protectedSet.has(branch)) {
                return;
            }
            if (options.blockEditsOnProtectedBranches && (tool === "write" || tool === "edit" || tool === "apply_patch")) {
                const sessionId = String(eventPayload.input?.sessionID ?? eventPayload.input?.sessionId ?? "");
                writeGatewayEventAudit(directory, {
                    hook: "workflow-conformance-guard",
                    stage: "skip",
                    reason_code: "edit_on_protected_branch_blocked",
                    session_id: sessionId,
                });
                throw new Error(`File edits are blocked on protected branch '${branch}'. Use a worktree feature branch.`);
            }
            if (tool !== "bash") {
                return;
            }
            const command = String(eventPayload.output?.args?.command ?? "").trim();
            if (isProtectedGitMutationCommand(command)) {
                const sessionId = String(eventPayload.input?.sessionID ?? eventPayload.input?.sessionId ?? "");
                writeGatewayEventAudit(directory, {
                    hook: "workflow-conformance-guard",
                    stage: "skip",
                    reason_code: "commit_on_protected_branch_blocked",
                    session_id: sessionId,
                });
                throw new Error(`Git commits are blocked on protected branch '${branch}'. Use a worktree feature branch.`);
            }
            if (isAllowedProtectedShellCommand(command)) {
                return;
            }
            const sessionId = String(eventPayload.input?.sessionID ?? eventPayload.input?.sessionId ?? "");
            writeGatewayEventAudit(directory, {
                hook: "workflow-conformance-guard",
                stage: "skip",
                reason_code: "bash_on_protected_branch_blocked",
                session_id: sessionId,
            });
            throw new Error(`Bash commands on protected branch '${branch}' are limited to inspection, validation, and exact sync commands (\`git fetch\`, \`git fetch --prune\`, and \`git pull --rebase\`). Use a worktree feature branch for task mutations.`);
        },
    };
}

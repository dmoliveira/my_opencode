import { execSync } from "node:child_process";
import { basename, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { writeGatewayEventAudit } from "../../audit/event-audit.js";
import { isAllowedProtectedShellCommand } from "../protected-shell-policy.js";
import { effectiveToolDirectory } from "../shared/effective-tool-directory.js";
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
function gitPath(directory, flag) {
    return resolve(directory, execSync(`git rev-parse ${flag}`, { cwd: directory, stdio: ["ignore", "pipe", "ignore"] })
        .toString("utf-8")
        .trim());
}
function isPrimaryWorktree(directory) {
    try {
        return gitPath(directory, "--git-dir") === gitPath(directory, "--git-common-dir");
    }
    catch {
        return false;
    }
}
const PROTECTED_GIT_MUTATION_PATTERN = /(?:^|&&|\|\||;)\s*(?:env\s+(?:[A-Za-z_][A-Za-z0-9_]*=(?:"[^"]*"|'[^']*'|\S+)\s+)*)?(?:(?:[^\s;&|]*\/)?rtk\s+)?(?:[^\s;&|]*\/)?git\s+(commit|merge|rebase|cherry-pick)\b/i;
function isProtectedGitMutationCommand(command) {
    return PROTECTED_GIT_MUTATION_PATTERN.test(command);
}
function protectedBranchWorktreeHint(directory) {
    const base = basename(directory) || "repo";
    return `For repo maintenance, run \`python3 scripts/worktree_helper_command.py maintenance --directory ${directory}\` or create a throwaway worktree directly, for example: \`git worktree add -b chore/<task> ../${base}-maint HEAD\`.`;
}
function shellQuote(value) {
    return JSON.stringify(value);
}
const MAINTENANCE_HELPER = fileURLToPath(new URL("../../../../../scripts/worktree_helper_command.py", import.meta.url));
function maintenanceHelperCommand(directory, originalCommand) {
    return `python3 ${shellQuote(MAINTENANCE_HELPER)} maintenance --directory ${shellQuote(directory)} --command ${shellQuote(originalCommand)} --json`;
}
function rerouteToMaintenanceHelper(payload, directory, sessionId, reasonCode) {
    const args = payload.output?.args;
    const originalCommand = typeof args?.command === "string" ? args.command.trim() : "";
    if (!args || !originalCommand) {
        return false;
    }
    args.command = maintenanceHelperCommand(directory, originalCommand);
    writeGatewayEventAudit(directory, {
        hook: "workflow-conformance-guard",
        stage: "state",
        reason_code: reasonCode,
        session_id: sessionId,
        blocked_command: originalCommand,
    });
    return true;
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
            const directory = effectiveToolDirectory(eventPayload, options.directory);
            if (!isPrimaryWorktree(directory)) {
                return;
            }
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
                if (rerouteToMaintenanceHelper(eventPayload, directory, sessionId, "commit_on_protected_branch_rerouted")) {
                    return;
                }
                throw new Error(`Git commits are blocked on protected branch '${branch}'. Use a worktree feature branch. ${protectedBranchWorktreeHint(directory)}`);
            }
            if (isAllowedProtectedShellCommand(command)) {
                return;
            }
            const sessionId = String(eventPayload.input?.sessionID ?? eventPayload.input?.sessionId ?? "");
            if (rerouteToMaintenanceHelper(eventPayload, directory, sessionId, "bash_on_protected_branch_rerouted")) {
                return;
            }
            throw new Error(`Bash commands on protected branch '${branch}' are limited to inspection, validation, and exact sync commands (\`git fetch\`, \`git fetch --prune\`, and \`git pull --rebase\`). Use a worktree feature branch for task mutations. ${protectedBranchWorktreeHint(directory)}`);
        },
    };
}

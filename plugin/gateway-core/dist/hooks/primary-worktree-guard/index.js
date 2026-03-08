import { execFileSync } from "node:child_process";
import { resolve } from "node:path";
import { writeGatewayEventAudit } from "../../audit/event-audit.js";
import { hasDisallowedShellSyntax, isAllowedProtectedShellCommand } from "../protected-shell-policy.js";
import { effectiveToolDirectory } from "../shared/effective-tool-directory.js";
function gitPath(directory, flag) {
    const output = execFileSync("git", ["rev-parse", flag], {
        cwd: directory,
        encoding: "utf-8",
        stdio: ["ignore", "pipe", "ignore"],
    }).trim();
    return resolve(directory, output);
}
function isPrimaryWorktree(directory) {
    try {
        return gitPath(directory, "--git-dir") === gitPath(directory, "--git-common-dir");
    }
    catch {
        return false;
    }
}
function stripQuotes(token) {
    return token.replace(/^['"]|['"]$/g, "");
}
const GIT_PREFIX = String.raw `(?:^|&&|\|\||;)\s*(?:env\s+(?:[A-Za-z_][A-Za-z0-9_]*=(?:"[^"]*"|'[^']*'|\S+)\s+)*)?(?:[^\s;&|]*/)?git\s+`;
function matchBranchTarget(command, pattern) {
    const match = command.match(pattern);
    return match?.[1] ? stripQuotes(match[1]) : null;
}
function hasPattern(command, pattern) {
    return pattern.test(command);
}
function branchSwitchInfo(command) {
    if (new RegExp(`${GIT_PREFIX}checkout\\s+(?:"[^"]+"|'[^']+'|[^\\s;&|]+)\\s+--\\s+`, "i").test(command)) {
        return null;
    }
    const destructiveTarget = matchBranchTarget(command, new RegExp(`${GIT_PREFIX}switch\\s+(?:-c|-C|--orphan)\\s+("[^"]+"|'[^']+'|[^\\s;&|]+)`, "i")) ??
        matchBranchTarget(command, new RegExp(`${GIT_PREFIX}checkout\\s+(?:-b|-B|--orphan)\\s+("[^"]+"|'[^']+'|[^\\s;&|]+)`, "i"));
    if (destructiveTarget) {
        return { target: destructiveTarget, plain: false };
    }
    if (hasPattern(command, new RegExp(`${GIT_PREFIX}switch\\s+--detach\\b`, "i"))) {
        return { target: "--detach", plain: false };
    }
    if (hasPattern(command, new RegExp(`${GIT_PREFIX}checkout\\s+--detach\\b`, "i"))) {
        return { target: "--detach", plain: false };
    }
    const plainTarget = matchBranchTarget(command, new RegExp(`${GIT_PREFIX}switch\\s+(?!-)("[^"]+"|'[^']+'|[^\\s;&|]+)`, "i")) ??
        matchBranchTarget(command, new RegExp(`${GIT_PREFIX}checkout\\s+(?!-)("[^"]+"|'[^']+'|[^\\s;&|]+)`, "i"));
    return plainTarget ? { target: plainTarget, plain: true } : null;
}
export function createPrimaryWorktreeGuardHook(options) {
    const allowedBranches = new Set(options.allowedBranches.map((item) => item.trim()).filter(Boolean));
    return {
        id: "primary-worktree-guard",
        priority: 689,
        async event(type, payload) {
            if (!options.enabled || type !== "tool.execute.before") {
                return;
            }
            const eventPayload = (payload ?? {});
            const directory = effectiveToolDirectory(eventPayload, options.directory);
            if (!isPrimaryWorktree(directory)) {
                return;
            }
            const tool = String(eventPayload.input?.tool ?? "").toLowerCase();
            const sessionId = String(eventPayload.input?.sessionID ?? eventPayload.input?.sessionId ?? "");
            if (options.blockEdits && (tool === "write" || tool === "edit" || tool === "apply_patch")) {
                writeGatewayEventAudit(directory, {
                    hook: "primary-worktree-guard",
                    stage: "skip",
                    reason_code: "edit_in_primary_worktree_blocked",
                    session_id: sessionId,
                });
                throw new Error("File edits are blocked in the primary project folder. Create or use a dedicated git worktree branch.");
            }
            if (!options.blockBranchSwitches || tool !== "bash") {
                return;
            }
            const command = String(eventPayload.output?.args?.command ?? "").trim();
            const switchInfo = branchSwitchInfo(command);
            if (switchInfo) {
                if (!hasDisallowedShellSyntax(command) && switchInfo.plain && allowedBranches.has(switchInfo.target)) {
                    return;
                }
                writeGatewayEventAudit(directory, {
                    hook: "primary-worktree-guard",
                    stage: "skip",
                    reason_code: "branch_switch_in_primary_worktree_blocked",
                    session_id: sessionId,
                    target_branch: switchInfo.target,
                });
                throw new Error(`Branch switching to '${switchInfo.target}' is blocked in the primary project folder. Create or use a dedicated git worktree branch instead.`);
            }
            if (isAllowedProtectedShellCommand(command)) {
                return;
            }
            writeGatewayEventAudit(directory, {
                hook: "primary-worktree-guard",
                stage: "skip",
                reason_code: "bash_in_primary_worktree_blocked",
                session_id: sessionId,
            });
            throw new Error("Bash commands in the primary project folder are limited to inspection, validation, and exact default-branch sync commands (`git fetch`, `git fetch --prune`, and `git pull --rebase`). Create or use a dedicated git worktree branch for task mutations.");
        },
    };
}

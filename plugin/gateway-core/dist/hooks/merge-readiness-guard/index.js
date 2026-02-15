import { writeGatewayEventAudit } from "../../audit/event-audit.js";
// Returns true when command is gh pr merge.
function isPrMerge(command) {
    return /\bgh\s+pr\s+merge\b/i.test(command);
}
// Returns true when command includes merge strategy flag.
function hasStrategy(command) {
    return /\s--merge\b|\s--squash\b|\s--rebase\b/i.test(command);
}
// Creates merge readiness guard for explicit safe merge command usage.
export function createMergeReadinessGuardHook(options) {
    return {
        id: "merge-readiness-guard",
        priority: 445,
        async event(type, payload) {
            if (!options.enabled || type !== "tool.execute.before") {
                return;
            }
            const eventPayload = (payload ?? {});
            if (String(eventPayload.input?.tool ?? "").toLowerCase() !== "bash") {
                return;
            }
            const command = String(eventPayload.output?.args?.command ?? "").trim();
            if (!isPrMerge(command)) {
                return;
            }
            const directory = typeof eventPayload.directory === "string" && eventPayload.directory.trim()
                ? eventPayload.directory
                : options.directory;
            const sessionId = String(eventPayload.input?.sessionID ?? eventPayload.input?.sessionId ?? "");
            const lower = command.toLowerCase();
            if (options.disallowAdminBypass && /\s--admin\b/.test(lower)) {
                writeGatewayEventAudit(directory, {
                    hook: "merge-readiness-guard",
                    stage: "skip",
                    reason_code: "merge_admin_bypass_blocked",
                    session_id: sessionId,
                });
                throw new Error("[merge-readiness-guard] `gh pr merge --admin` is blocked by policy.");
            }
            if (options.requireStrategy && !hasStrategy(lower)) {
                writeGatewayEventAudit(directory, {
                    hook: "merge-readiness-guard",
                    stage: "skip",
                    reason_code: "merge_strategy_missing",
                    session_id: sessionId,
                });
                throw new Error("[merge-readiness-guard] Merge strategy flag is required (--merge/--squash/--rebase).");
            }
            if (options.requireDeleteBranch && !/\s--delete-branch\b/.test(lower)) {
                writeGatewayEventAudit(directory, {
                    hook: "merge-readiness-guard",
                    stage: "skip",
                    reason_code: "merge_delete_branch_missing",
                    session_id: sessionId,
                });
                throw new Error("[merge-readiness-guard] Include `--delete-branch` when merging PRs.");
            }
        },
    };
}

import { execFileSync } from "node:child_process";
import { writeGatewayEventAudit } from "../../audit/event-audit.js";
import { extractGitHubPrMergeSelector, isGitHubPrMergeCommand } from "../shared/github-pr-commands.js";
const SUCCESS_CONCLUSIONS = new Set(["SUCCESS", "NEUTRAL", "SKIPPED"]);
const PENDING_CONCLUSIONS = new Set(["PENDING", "IN_PROGRESS", "QUEUED", "WAITING", "EXPECTED", "REQUESTED"]);
const PENDING_STATUSES = new Set(["PENDING", "IN_PROGRESS", "QUEUED", "WAITING", "EXPECTED", "REQUESTED"]);
// Normalizes token into uppercase trimmed string.
function normalize(value) {
    return String(value ?? "")
        .trim()
        .toUpperCase();
}
// Loads PR metadata from gh cli for merge checks.
function loadPrView(input) {
    const args = ["pr", "view"];
    if (input.selector.trim()) {
        args.push(input.selector.trim());
    }
    args.push("--json", "isDraft,reviewDecision,mergeStateStatus,statusCheckRollup");
    const output = execFileSync("gh", args, {
        cwd: input.directory,
        stdio: ["ignore", "pipe", "pipe"],
    })
        .toString("utf-8")
        .trim();
    return JSON.parse(output);
}
// Classifies status check rollup into failed and pending buckets.
function summarizeChecks(rollup) {
    if (!Array.isArray(rollup)) {
        return { total: 0, failed: 0, pending: 0 };
    }
    let failed = 0;
    let pending = 0;
    for (const entry of rollup) {
        const conclusion = normalize(entry.conclusion ?? entry.state);
        const status = normalize(entry.status);
        if (conclusion) {
            if (SUCCESS_CONCLUSIONS.has(conclusion)) {
                continue;
            }
            if (PENDING_CONCLUSIONS.has(conclusion)) {
                pending += 1;
                continue;
            }
            failed += 1;
            continue;
        }
        if (status) {
            if (status === "COMPLETED" || status === "SUCCESS" || status === "SUCCESSFUL") {
                continue;
            }
            if (PENDING_STATUSES.has(status)) {
                pending += 1;
                continue;
            }
            failed += 1;
            continue;
        }
        pending += 1;
    }
    return {
        total: rollup.length,
        failed,
        pending,
    };
}
// Creates merge checks guard that requires draft/review/check readiness before merge.
export function createGhChecksMergeGuardHook(options) {
    const blockedStates = new Set(options.blockedMergeStates.map((item) => normalize(item)).filter(Boolean));
    const inspectPr = options.inspectPr ?? loadPrView;
    return {
        id: "gh-checks-merge-guard",
        priority: 446,
        async event(type, payload) {
            if (!options.enabled || type !== "tool.execute.before") {
                return;
            }
            const eventPayload = (payload ?? {});
            if (String(eventPayload.input?.tool ?? "").toLowerCase() !== "bash") {
                return;
            }
            const command = String(eventPayload.output?.args?.command ?? "").trim();
            if (!isGitHubPrMergeCommand(command)) {
                return;
            }
            const directory = typeof eventPayload.directory === "string" && eventPayload.directory.trim()
                ? eventPayload.directory
                : options.directory;
            const sessionId = String(eventPayload.input?.sessionID ?? eventPayload.input?.sessionId ?? "");
            const selector = extractGitHubPrMergeSelector(command);
            let prView;
            try {
                prView = inspectPr({
                    directory,
                    selector,
                });
            }
            catch (error) {
                writeGatewayEventAudit(directory, {
                    hook: "gh-checks-merge-guard",
                    stage: "skip",
                    reason_code: "merge_checks_lookup_failed",
                    session_id: sessionId,
                    selector,
                });
                if (options.failOpenOnError) {
                    return;
                }
                throw new Error(`[gh-checks-merge-guard] Unable to verify PR checks before merge: ${error instanceof Error ? error.message : String(error)}.`);
            }
            const isDraft = Boolean(prView.isDraft);
            const reviewDecision = normalize(prView.reviewDecision);
            const mergeState = normalize(prView.mergeStateStatus);
            const checks = summarizeChecks(prView.statusCheckRollup);
            if (options.blockDraft && isDraft) {
                writeGatewayEventAudit(directory, {
                    hook: "gh-checks-merge-guard",
                    stage: "skip",
                    reason_code: "merge_draft_blocked",
                    session_id: sessionId,
                    selector,
                });
                throw new Error("[gh-checks-merge-guard] PR is draft. Mark ready for review before merging.");
            }
            if (blockedStates.has(mergeState)) {
                writeGatewayEventAudit(directory, {
                    hook: "gh-checks-merge-guard",
                    stage: "skip",
                    reason_code: "merge_state_blocked",
                    session_id: sessionId,
                    selector,
                    merge_state: mergeState,
                });
                throw new Error(`[gh-checks-merge-guard] PR merge state '${mergeState}' is blocked by policy.`);
            }
            if (options.requireApprovedReview && reviewDecision !== "APPROVED") {
                writeGatewayEventAudit(directory, {
                    hook: "gh-checks-merge-guard",
                    stage: "skip",
                    reason_code: "merge_review_not_approved",
                    session_id: sessionId,
                    selector,
                    review_decision: reviewDecision,
                });
                throw new Error(`[gh-checks-merge-guard] Review decision is '${reviewDecision || "UNKNOWN"}'. Approval is required before merge.`);
            }
            if (options.requirePassingChecks && (checks.failed > 0 || checks.pending > 0)) {
                writeGatewayEventAudit(directory, {
                    hook: "gh-checks-merge-guard",
                    stage: "skip",
                    reason_code: "merge_checks_not_green",
                    session_id: sessionId,
                    selector,
                    checks_failed: checks.failed,
                    checks_pending: checks.pending,
                    checks_total: checks.total,
                });
                throw new Error(`[gh-checks-merge-guard] PR checks are not green (failed=${checks.failed}, pending=${checks.pending}).`);
            }
            writeGatewayEventAudit(directory, {
                hook: "gh-checks-merge-guard",
                stage: "state",
                reason_code: "merge_checks_verified",
                session_id: sessionId,
                selector,
                checks_total: checks.total,
            });
        },
    };
}

import { writeGatewayEventAudit } from "../../audit/event-audit.js";
import { inspectGitHubPrCreateBody, isGitHubPrCreateCommand } from "../shared/github-pr-commands.js";
import { validationEvidenceStatus } from "../validation-evidence-ledger/evidence.js";
// Creates PR body evidence guard for structured PR metadata quality.
export function createPrBodyEvidenceGuardHook(options) {
    const requiredMarkers = options.requiredMarkers.map((item) => item.trim().toLowerCase()).filter(Boolean);
    return {
        id: "pr-body-evidence-guard",
        priority: 442,
        async event(type, payload) {
            if (!options.enabled || type !== "tool.execute.before") {
                return;
            }
            const eventPayload = (payload ?? {});
            if (String(eventPayload.input?.tool ?? "").toLowerCase() !== "bash") {
                return;
            }
            const command = String(eventPayload.output?.args?.command ?? "");
            if (!isGitHubPrCreateCommand(command)) {
                return;
            }
            const directory = typeof eventPayload.directory === "string" && eventPayload.directory.trim()
                ? eventPayload.directory
                : options.directory;
            const sessionId = String(eventPayload.input?.sessionID ?? eventPayload.input?.sessionId ?? "").trim();
            if (options.requireValidationEvidence && sessionId && requiredMarkers.length > 0) {
                const status = validationEvidenceStatus(sessionId, requiredMarkers, directory);
                if (status.missing.length > 0) {
                    writeGatewayEventAudit(directory, {
                        hook: "pr-body-evidence-guard",
                        stage: "skip",
                        reason_code: "pr_body_missing_validation_evidence",
                        session_id: sessionId,
                    });
                    throw new Error(`[pr-body-evidence-guard] Missing validation evidence before PR create: ${status.missing.join(", ")}. Evidence must be recorded in this session or the current worktree before PR creation.`);
                }
            }
            const inspection = inspectGitHubPrCreateBody(command, directory);
            if (!inspection.inspectable) {
                if (options.allowUninspectableBody) {
                    return;
                }
                writeGatewayEventAudit(directory, {
                    hook: "pr-body-evidence-guard",
                    stage: "skip",
                    reason_code: "pr_body_uninspectable",
                    session_id: sessionId,
                });
                throw new Error("[pr-body-evidence-guard] PR body is missing or uninspectable. Use --body/--body-file with Summary and Validation sections.");
            }
            const body = inspection.body;
            const hasSummary = /(^|\n)\s*##\s*summary\b/i.test(body);
            const hasValidation = /(^|\n)\s*##\s*validation\b/i.test(body);
            if (options.requireSummarySection && !hasSummary) {
                writeGatewayEventAudit(directory, {
                    hook: "pr-body-evidence-guard",
                    stage: "skip",
                    reason_code: "pr_body_missing_summary_section",
                    session_id: sessionId,
                });
                throw new Error("[pr-body-evidence-guard] PR body must include a '## Summary' section.");
            }
            if (options.requireValidationSection && !hasValidation) {
                writeGatewayEventAudit(directory, {
                    hook: "pr-body-evidence-guard",
                    stage: "skip",
                    reason_code: "pr_body_missing_validation_section",
                    session_id: sessionId,
                });
                throw new Error("[pr-body-evidence-guard] PR body must include a '## Validation' section.");
            }
        },
    };
}

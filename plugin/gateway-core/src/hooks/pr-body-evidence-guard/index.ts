import { writeGatewayEventAudit } from "../../audit/event-audit.js"
import type { GatewayHook } from "../registry.js"
import type { LlmDecisionRuntime } from "../shared/llm-decision-runtime.js"
import { inspectGitHubPrCreateBody, isGitHubPrCreateCommand } from "../shared/github-pr-commands.js"
import { validationEvidenceStatus } from "../validation-evidence-ledger/evidence.js"

interface ToolBeforePayload {
  input?: {
    tool?: string
    sessionID?: string
    sessionId?: string
  }
  output?: {
    args?: { command?: string }
  }
  directory?: string
}

function buildSectionInstruction(section: "summary" | "validation"): string {
  return section === "summary"
    ? "Does this PR body contain summary-equivalent content? Y=yes, N=no."
    : "Does this PR body contain validation-or-testing-equivalent content? Y=yes, N=no."
}

function buildSectionContext(body: string): string {
  return `body=${body.trim() || "(empty)"}`
}

// Creates PR body evidence guard for structured PR metadata quality.
export function createPrBodyEvidenceGuardHook(options: {
  directory: string
  enabled: boolean
  requireSummarySection: boolean
  requireValidationSection: boolean
  requireValidationEvidence: boolean
  allowUninspectableBody: boolean
  requiredMarkers: string[]
  decisionRuntime?: LlmDecisionRuntime
}): GatewayHook {
  const requiredMarkers = options.requiredMarkers.map((item) => item.trim().toLowerCase()).filter(Boolean)
  return {
    id: "pr-body-evidence-guard",
    priority: 442,
    async event(type: string, payload: unknown): Promise<void> {
      if (!options.enabled || type !== "tool.execute.before") {
        return
      }
      const eventPayload = (payload ?? {}) as ToolBeforePayload
      if (String(eventPayload.input?.tool ?? "").toLowerCase() !== "bash") {
        return
      }
      const command = String(eventPayload.output?.args?.command ?? "")
      if (!isGitHubPrCreateCommand(command)) {
        return
      }
      const directory =
        typeof eventPayload.directory === "string" && eventPayload.directory.trim()
          ? eventPayload.directory
          : options.directory
      const sessionId = String(eventPayload.input?.sessionID ?? eventPayload.input?.sessionId ?? "").trim()

      if (options.requireValidationEvidence && sessionId && requiredMarkers.length > 0) {
        const status = validationEvidenceStatus(sessionId, requiredMarkers, directory)
        if (status.missing.length > 0) {
          writeGatewayEventAudit(directory, {
            hook: "pr-body-evidence-guard",
            stage: "skip",
            reason_code: "pr_body_missing_validation_evidence",
            session_id: sessionId,
          })
          throw new Error(
            `[pr-body-evidence-guard] Missing validation evidence before PR create: ${status.missing.join(
              ", ",
            )}. Evidence must be recorded in this session or the current worktree before PR creation.`,
          )
        }
      }

      const inspection = inspectGitHubPrCreateBody(command, directory)
      if (!inspection.inspectable) {
        if (options.allowUninspectableBody) {
          return
        }
        writeGatewayEventAudit(directory, {
          hook: "pr-body-evidence-guard",
          stage: "skip",
          reason_code: "pr_body_uninspectable",
          session_id: sessionId,
        })
        throw new Error(
          "[pr-body-evidence-guard] PR body is missing or uninspectable. Use --body/--body-file with Summary and Validation sections.",
        )
      }

      const body = inspection.body
      let hasSummary = /(^|\n)\s*##\s*summary\b/i.test(body)
      let hasValidation = /(^|\n)\s*##\s*validation\b/i.test(body)

      if ((!hasSummary || !hasValidation) && options.decisionRuntime) {
        if (!hasSummary) {
          const decision = await options.decisionRuntime.decide({
            hookId: "pr-body-evidence-guard",
            sessionId,
            templateId: "pr-body-summary-v1",
            instruction: buildSectionInstruction("summary"),
            context: buildSectionContext(body),
            allowedChars: ["Y", "N"],
            decisionMeaning: { Y: "summary_present", N: "summary_missing" },
            cacheKey: `pr-body-summary:${body.trim().toLowerCase()}`,
          })
          if (decision.accepted) {
            hasSummary = decision.char === "Y"
            writeGatewayEventAudit(directory, {
              hook: "pr-body-evidence-guard",
              stage: "state",
              reason_code: "llm_pr_body_summary_decision_recorded",
              session_id: sessionId,
              llm_decision_char: decision.char,
              llm_decision_meaning: decision.meaning,
              llm_decision_mode: options.decisionRuntime.config.mode,
            })
          }
        }
        if (!hasValidation) {
          const decision = await options.decisionRuntime.decide({
            hookId: "pr-body-evidence-guard",
            sessionId,
            templateId: "pr-body-validation-v1",
            instruction: buildSectionInstruction("validation"),
            context: buildSectionContext(body),
            allowedChars: ["Y", "N"],
            decisionMeaning: { Y: "validation_present", N: "validation_missing" },
            cacheKey: `pr-body-validation:${body.trim().toLowerCase()}`,
          })
          if (decision.accepted) {
            hasValidation = decision.char === "Y"
            writeGatewayEventAudit(directory, {
              hook: "pr-body-evidence-guard",
              stage: "state",
              reason_code: "llm_pr_body_validation_decision_recorded",
              session_id: sessionId,
              llm_decision_char: decision.char,
              llm_decision_meaning: decision.meaning,
              llm_decision_mode: options.decisionRuntime.config.mode,
            })
          }
        }
      }

      if (options.requireSummarySection && !hasSummary) {
        writeGatewayEventAudit(directory, {
          hook: "pr-body-evidence-guard",
          stage: "skip",
          reason_code: "pr_body_missing_summary_section",
          session_id: sessionId,
        })
        throw new Error("[pr-body-evidence-guard] PR body must include a '## Summary' section.")
      }
      if (options.requireValidationSection && !hasValidation) {
        writeGatewayEventAudit(directory, {
          hook: "pr-body-evidence-guard",
          stage: "skip",
          reason_code: "pr_body_missing_validation_section",
          session_id: sessionId,
        })
        throw new Error("[pr-body-evidence-guard] PR body must include a '## Validation' section.")
      }
    },
  }
}

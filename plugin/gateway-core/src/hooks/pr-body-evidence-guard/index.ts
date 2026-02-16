import { readFileSync } from "node:fs"
import { resolve } from "node:path"

import { writeGatewayEventAudit } from "../../audit/event-audit.js"
import type { GatewayHook } from "../registry.js"
import { missingValidationMarkers } from "../validation-evidence-ledger/evidence.js"

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

interface BodyInspection {
  body: string
  inspectable: boolean
}

// Returns true when command triggers PR creation.
function isPrCreate(command: string): boolean {
  return /\bgh\s+pr\s+create\b/i.test(command)
}

// Tokenizes command string with basic quote support.
function tokenize(command: string): string[] {
  const matches = command.match(/"[^"]*"|'[^']*'|\S+/g)
  if (!matches) {
    return []
  }
  return matches.map((token) => {
    if (token.length >= 2 && ((token.startsWith('"') && token.endsWith('"')) || (token.startsWith("'") && token.endsWith("'")))) {
      return token.slice(1, -1)
    }
    return token
  })
}

// Resolves PR body text from command flags when available.
function inspectBody(command: string, directory: string): BodyInspection {
  const tokens = tokenize(command)
  for (let index = 0; index < tokens.length; index += 1) {
    const token = tokens[index]
    if (token === "--body" && index + 1 < tokens.length) {
      return {
        body: tokens[index + 1],
        inspectable: true,
      }
    }
    if (token.startsWith("--body=")) {
      return {
        body: token.slice("--body=".length),
        inspectable: true,
      }
    }
    if (token === "--body-file" && index + 1 < tokens.length) {
      try {
        const content = readFileSync(resolve(directory, tokens[index + 1]), "utf-8")
        return {
          body: content,
          inspectable: true,
        }
      } catch {
        return {
          body: "",
          inspectable: false,
        }
      }
    }
    if (token.startsWith("--body-file=")) {
      try {
        const content = readFileSync(resolve(directory, token.slice("--body-file=".length)), "utf-8")
        return {
          body: content,
          inspectable: true,
        }
      } catch {
        return {
          body: "",
          inspectable: false,
        }
      }
    }
  }
  return {
    body: "",
    inspectable: false,
  }
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
      if (!isPrCreate(command)) {
        return
      }
      const directory =
        typeof eventPayload.directory === "string" && eventPayload.directory.trim()
          ? eventPayload.directory
          : options.directory
      const sessionId = String(eventPayload.input?.sessionID ?? eventPayload.input?.sessionId ?? "").trim()

      if (options.requireValidationEvidence && sessionId && requiredMarkers.length > 0) {
        const missing = missingValidationMarkers(sessionId, requiredMarkers)
        if (missing.length > 0) {
          writeGatewayEventAudit(directory, {
            hook: "pr-body-evidence-guard",
            stage: "skip",
            reason_code: "pr_body_missing_validation_evidence",
            session_id: sessionId,
          })
          throw new Error(
            `[pr-body-evidence-guard] Missing validation evidence before PR create: ${missing.join(", ")}.`,
          )
        }
      }

      const inspection = inspectBody(command, directory)
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
      const hasSummary = /(^|\n)\s*##\s*summary\b/i.test(body)
      const hasValidation = /(^|\n)\s*##\s*validation\b/i.test(body)

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

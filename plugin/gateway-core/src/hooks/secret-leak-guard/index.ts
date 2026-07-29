import { writeGatewayEventAudit } from "../../audit/event-audit.js"
import type { GatewayHook } from "../registry.js"
import {
  createSecretRedactor,
  type SecretRedactionLimits,
  type SecretRedactionStats,
} from "../shared/secret-redaction.js"

interface ToolAfterPayload {
  input?: {
    tool?: string
    sessionID?: string
    sessionId?: string
  }
  output?: {
    output?: unknown
  }
  directory?: string
}

function mergeStats(target: SecretRedactionStats, source: SecretRedactionStats): void {
  target.matches += source.matches
  target.redactedFields += source.redactedFields
  target.scannedChars += source.scannedChars
  target.scannedNodes += source.scannedNodes
  target.omittedOpaqueAttachmentMatches += source.omittedOpaqueAttachmentMatches
}

// Creates secret leak guard hook that redacts likely secrets from every tool output channel.
export function createSecretLeakGuardHook(options: {
  directory: string
  enabled: boolean
  redactionToken: string
  patterns: string[]
  limits: SecretRedactionLimits
}): GatewayHook {
  const redactor = createSecretRedactor(options)
  return {
    id: "secret-leak-guard",
    priority: 395,
    events: ["tool.execute.after"],
    async event(type: string, payload: unknown): Promise<void> {
      if (!options.enabled || type !== "tool.execute.after") {
        return
      }
      const eventPayload = (payload ?? {}) as ToolAfterPayload
      const mutableOutput = eventPayload.output
      if (!mutableOutput) {
        return
      }
      const rawOutput = mutableOutput.output
      const stats: SecretRedactionStats = {
        matches: 0,
        redactedFields: 0,
        scannedChars: 0,
        scannedNodes: 0,
        omittedOpaqueAttachmentMatches: 0,
      }
      const outputShape = typeof rawOutput === "string" ? "string" : "structured"

      if (typeof rawOutput === "string") {
        const result = redactor.redactText(rawOutput)
        mergeStats(stats, result.stats)
        if (result.text !== rawOutput) {
          mutableOutput.output = result.text
        }
      } else if (rawOutput && typeof rawOutput === "object") {
        mergeStats(stats, redactor.redactMutableValue(rawOutput))
      } else {
        return
      }

      if (stats.matches === 0) {
        return
      }
      const directory = eventPayload.directory?.trim() || options.directory
      const sessionId = String(
        eventPayload.input?.sessionID ?? eventPayload.input?.sessionId ?? "",
      )
      writeGatewayEventAudit(directory, {
        hook: "secret-leak-guard",
        stage: "state",
        reason_code: "secret_output_redacted",
        session_id: sessionId,
        match_count: stats.matches,
        redacted_field_count: stats.redactedFields,
        scanned_chars: stats.scannedChars,
        output_shape: outputShape,
      })
    },
  }
}

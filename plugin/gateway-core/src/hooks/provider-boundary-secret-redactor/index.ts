import { isProxy } from "node:util/types"

import {
  gatewayAuditSessionFields,
  normalizeGatewayAuditSessionId,
  writeGatewayEventAudit,
} from "../../audit/event-audit.js"
import {
  createSecretRedactor,
  SecretRedactionError,
  type ProviderSecretRedactionLimits,
  type SecretRedactionLimits,
  type SecretRedactionStats,
} from "../shared/secret-redaction.js"

export interface ProviderBoundarySecretFinalizer {
  finalizeMessages(payload: {
    input?: { sessionID?: string }
    output?: { messages?: unknown }
    directory?: string
  }): void
  finalizeSystem(payload: {
    input?: { sessionID?: string }
    output?: { system?: unknown }
    directory?: string
  }): void
}

function messageSessionId(messages: unknown, maxMessages: number): string {
  if (!Array.isArray(messages) || isProxy(messages)) {
    return ""
  }
  const limit = Number.isFinite(maxMessages) && maxMessages > 0 ? Math.floor(maxMessages) : 0
  if (limit === 0 || messages.length > limit) {
    return ""
  }
  for (let index = 0; index < messages.length && index < limit; index += 1) {
    const message = ownDataValue(messages, index)
    const info = ownDataValue(message, "info")
    const sessionID = ownDataValue(info, "sessionID")
    const normalized = normalizeGatewayAuditSessionId(sessionID)
    if (normalized) return normalized
  }
  return ""
}

function ownDataValue(value: unknown, key: PropertyKey): unknown {
  if (!value || typeof value !== "object" || isProxy(value)) return undefined
  try {
    const descriptor = Object.getOwnPropertyDescriptor(value, key)
    return descriptor && "value" in descriptor ? descriptor.value : undefined
  } catch {
    return undefined
  }
}

function auditRedaction(
  directory: string,
  surface: "messages" | "system",
  sessionId: string,
  stats: SecretRedactionStats,
): void {
  if (stats.matches === 0) {
    return
  }
  writeGatewayEventAudit(directory, {
    hook: "provider-boundary-secret-redactor",
    stage: "state",
    reason_code: "provider_boundary_secrets_redacted",
    surface,
    ...gatewayAuditSessionFields(sessionId),
    match_count: stats.matches,
    redacted_field_count: stats.redactedFields,
    scanned_chars: stats.scannedChars,
    scanned_nodes: stats.scannedNodes,
  })
}

function auditOpaqueAttachmentOmission(
  directory: string,
  surface: "messages" | "system",
  sessionId: string,
  stats: SecretRedactionStats,
): void {
  if (stats.omittedOpaqueAttachmentMatches === 0) return
  writeGatewayEventAudit(directory, {
    hook: "provider-boundary-secret-redactor",
    stage: "state",
    reason_code: "provider_boundary_opaque_attachment_collision_omitted",
    surface,
    ...gatewayAuditSessionFields(sessionId),
    omitted_match_count: stats.omittedOpaqueAttachmentMatches,
  })
}

export function createProviderBoundarySecretFinalizer(options: {
  directory: string
  patterns: string[]
  redactionToken: string
  limits: SecretRedactionLimits
  providerLimits: ProviderSecretRedactionLimits
  omittableOpaqueAttachmentPatternIndex?: number | null
}): ProviderBoundarySecretFinalizer {
  const redactor = createSecretRedactor(options)

  function blockAudit(
    directory: string,
    surface: "messages" | "system",
    sessionId: string,
    error: unknown,
  ): never {
    const code = error instanceof SecretRedactionError ? error.code : "unexpected_failure"
    const matchDiagnostics =
      error instanceof SecretRedactionError && error.code === "immutable_match"
        ? {
            match_target: error.matchTarget,
            pattern_index: error.patternIndex,
            location_code: error.locationCode,
          }
        : {}
    writeGatewayEventAudit(directory, {
      hook: "provider-boundary-secret-redactor",
      stage: "guard",
      reason_code: "provider_boundary_secret_dispatch_blocked",
      surface,
      ...gatewayAuditSessionFields(sessionId),
      error_code: code,
      ...matchDiagnostics,
    })
    if (error instanceof SecretRedactionError) {
      throw error
    }
    throw new SecretRedactionError("unexpected_failure")
  }

  return {
    finalizeMessages(payload): void {
      const messages = payload.output?.messages
      if (messages === undefined) {
        return
      }
      const directory = payload.directory?.trim() || options.directory
      let sessionId = normalizeGatewayAuditSessionId(payload.input?.sessionID)
      try {
        if (!Array.isArray(messages)) {
          throw new SecretRedactionError("malformed_provider_object")
        }
        if (!sessionId) {
          sessionId = messageSessionId(messages, options.providerLimits.maxMessages)
        }
        const stats = redactor.redactProviderMessages(messages)
        auditOpaqueAttachmentOmission(directory, "messages", sessionId, stats)
        auditRedaction(directory, "messages", sessionId, stats)
      } catch (error) {
        blockAudit(directory, "messages", sessionId, error)
      }
    },
    finalizeSystem(payload): void {
      const system = payload.output?.system
      if (system === undefined) {
        return
      }
      const directory = payload.directory?.trim() || options.directory
      const sessionId = normalizeGatewayAuditSessionId(payload.input?.sessionID)
      try {
        if (!Array.isArray(system)) {
          throw new SecretRedactionError("malformed_provider_object")
        }
        const stats = redactor.redactProviderSystem(system)
        auditRedaction(directory, "system", sessionId, stats)
      } catch (error) {
        blockAudit(directory, "system", sessionId, error)
      }
    },
  }
}

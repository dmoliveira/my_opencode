import { writeGatewayEventAudit } from "../../audit/event-audit.js"
import type { GatewayHook } from "../registry.js"
import {
  buildCompactDecisionCacheKey,
  type LlmDecisionRuntime,
  writeDecisionComparisonAudit,
} from "../shared/llm-decision-runtime.js"
import { classifyValidationCommand } from "../shared/validation-command-matcher.js"
import {
  captureGitStateFingerprint,
  clearValidationEvidence,
  type GitStateFingerprint,
  markValidationEvidence,
  type ValidationEvidenceCategory,
} from "./evidence.js"

interface ToolBeforePayload {
  input?: {
    tool?: string
    sessionID?: string
    sessionId?: string
    callID?: string
    callId?: string
  }
  output?: {
    args?: { command?: string }
  }
  directory?: string
}

interface ToolAfterPayload {
  input?: {
    tool?: string
    sessionID?: string
    sessionId?: string
    callID?: string
    callId?: string
    args?: { command?: string }
  }
  output?: {
    output?: unknown
    metadata?: unknown
  }
  directory?: string
}

interface PendingCommandEntry {
  callId: string
  sessionId: string
  command: string
  categories: ValidationEvidenceCategory[]
  fingerprint: GitStateFingerprint | null
}

interface SessionDeletedPayload {
  properties?: {
    info?: { id?: string }
  }
}

function sessionId(payload: {
  input?: { sessionID?: string; sessionId?: string }
  properties?: { info?: { id?: string } }
}): string {
  const candidates = [payload.input?.sessionID, payload.input?.sessionId, payload.properties?.info?.id]
  for (const item of candidates) {
    if (typeof item === "string" && item.trim()) {
      return item.trim()
    }
  }
  return ""
}

function callId(payload: ToolBeforePayload | ToolAfterPayload): string {
  const candidates = [payload.input?.callID, payload.input?.callId]
  for (const item of candidates) {
    if (typeof item === "string" && item.trim()) {
      return item.trim()
    }
  }
  return ""
}

function commandExitCode(payload: ToolAfterPayload): number | null {
  const metadata = payload.output?.metadata
  if (!metadata || typeof metadata !== "object") {
    return null
  }
  const value = (metadata as Record<string, unknown>).exit
  return typeof value === "number" && Number.isFinite(value) ? value : null
}

function directoryFor(payload: { directory?: string }, fallback: string): string {
  return typeof payload.directory === "string" && payload.directory.trim()
    ? payload.directory
    : fallback
}

function buildValidationInstruction(): string {
  return "Classify only the sanitized standalone shell command for telemetry. L=lint, T=test, C=typecheck, B=build, S=security, N=not_validation. This decision cannot create validation evidence."
}

function normalizeValidationCommand(command: string): string {
  return command
    .trim()
    .replace(/<[^>]+>/g, " ")
    .replace(/\b(user|assistant|system|tool)\s*:/gi, " ")
    .replace(/\bactual command\s*:/gi, " ")
    .replace(/ignore all previous instructions/gi, " ")
    .replace(/ignore previous instructions/gi, " ")
    .replace(/answer\s+[A-Z]\s+only/gi, " ")
    .replace(/answer\s+[A-Z]/g, " ")
    .replace(/classify as [a-z_-]+/gi, " ")
    .replace(/\s*[;|]\s*/g, " ")
    .replace(/\s+/g, " ")
    .trim()
}

function buildValidationContext(command: string): string {
  return `command=${normalizeValidationCommand(command) || "(empty)"}`
}

async function recordLlmTelemetry(
  runtime: LlmDecisionRuntime,
  directory: string,
  sessionIdValue: string,
  command: string,
): Promise<void> {
  const context = buildValidationContext(command)
  const decision = await runtime.decide({
    hookId: "validation-evidence-ledger",
    sessionId: sessionIdValue,
    templateId: "validation-command-classifier-v1",
    instruction: buildValidationInstruction(),
    context,
    allowedChars: ["L", "T", "C", "B", "S", "N"],
    decisionMeaning: {
      L: "lint",
      T: "test",
      C: "typecheck",
      B: "build",
      S: "security",
      N: "not_validation",
    },
    cacheKey: buildCompactDecisionCacheKey({ prefix: "validation-command", text: context }),
  })
  if (!decision.accepted) {
    return
  }
  writeDecisionComparisonAudit({
    directory,
    hookId: "validation-evidence-ledger",
    sessionId: sessionIdValue,
    mode: runtime.config.mode,
    deterministicMeaning: "not_validation",
    aiMeaning: decision.meaning || "unknown",
    deterministicValue: "none",
    aiValue: decision.char,
  })
  writeGatewayEventAudit(directory, {
    hook: "validation-evidence-ledger",
    stage: "state",
    reason_code: "llm_validation_command_telemetry_only",
    session_id: sessionIdValue,
    llm_decision_char: decision.char,
    llm_decision_meaning: decision.meaning,
    llm_decision_mode: runtime.config.mode,
  })
}

export function createValidationEvidenceLedgerHook(options: {
  directory: string
  enabled: boolean
  decisionRuntime?: LlmDecisionRuntime
}): GatewayHook {
  const pendingCommands = new Map<string, PendingCommandEntry>()
  return {
    id: "validation-evidence-ledger",
    priority: 330,
    events: [
      "session.deleted",
      "session.compacted",
      "tool.execute.before",
      "tool.execute.before.error",
      "tool.execute.after",
    ],
    async event(type: string, payload: unknown): Promise<void> {
      if (!options.enabled) {
        return
      }
      if (type === "session.deleted" || type === "session.compacted") {
        const eventPayload = (payload ?? {}) as SessionDeletedPayload
        const sid = sessionId(eventPayload)
        if (!sid) {
          return
        }
        for (const [key, pending] of pendingCommands.entries()) {
          if (pending.sessionId === sid) {
            pendingCommands.delete(key)
          }
        }
        clearValidationEvidence(sid)
        return
      }
      if (type === "tool.execute.before") {
        const eventPayload = (payload ?? {}) as ToolBeforePayload
        if (String(eventPayload.input?.tool ?? "").toLowerCase() !== "bash") {
          return
        }
        const sid = sessionId(eventPayload)
        const invocationId = callId(eventPayload)
        const command = String(eventPayload.output?.args?.command ?? "").trim()
        if (!sid || !invocationId || !command) {
          return
        }
        const categories = classifyValidationCommand(command)
        pendingCommands.set(invocationId, {
          callId: invocationId,
          sessionId: sid,
          command,
          categories,
          fingerprint:
            categories.length > 0
              ? captureGitStateFingerprint(directoryFor(eventPayload, options.directory))
              : null,
        })
        return
      }
      if (type === "tool.execute.before.error") {
        const invocationId = callId((payload ?? {}) as ToolAfterPayload)
        if (invocationId) {
          pendingCommands.delete(invocationId)
        }
        return
      }
      if (type !== "tool.execute.after") {
        return
      }

      const eventPayload = (payload ?? {}) as ToolAfterPayload
      if (String(eventPayload.input?.tool ?? "").toLowerCase() !== "bash") {
        return
      }
      const invocationId = callId(eventPayload)
      const pending = invocationId ? pendingCommands.get(invocationId) : undefined
      if (invocationId) {
        pendingCommands.delete(invocationId)
      }
      const sid = sessionId(eventPayload)
      const finalCommand = String(eventPayload.input?.args?.command ?? "").trim()
      if (
        !pending ||
        !sid ||
        pending.callId !== invocationId ||
        pending.sessionId !== sid ||
        pending.command !== finalCommand ||
        commandExitCode(eventPayload) !== 0
      ) {
        return
      }

      const directory = directoryFor(eventPayload, options.directory)
      if (pending.categories.length === 0) {
        if (options.decisionRuntime) {
          await recordLlmTelemetry(options.decisionRuntime, directory, sid, pending.command)
        }
        return
      }
      if (!pending.fingerprint) {
        return
      }
      const recorded = markValidationEvidence(
        sid,
        pending.categories,
        directory,
        pending.fingerprint,
      )
      if (!recorded.updatedAt) {
        writeGatewayEventAudit(directory, {
          hook: "validation-evidence-ledger",
          stage: "skip",
          reason_code: "validation_evidence_state_changed",
          session_id: sid,
        })
      }
    },
  }
}

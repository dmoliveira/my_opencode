import { writeGatewayEventAudit } from "../../audit/event-audit.js"
import type { GatewayHook } from "../registry.js"
import {
  type LlmDecisionRuntime,
  writeDecisionComparisonAudit,
} from "../shared/llm-decision-runtime.js"
import {
  clearValidationEvidence,
  markValidationEvidence,
} from "./evidence.js"
import { classifyValidationCommand } from "../shared/validation-command-matcher.js"
import type { ValidationEvidenceCategory } from "./evidence.js"

const VALIDATION_INVOCATION_ID_KEY = "validationEvidenceInvocationId"

interface ToolBeforePayload {
  input?: {
    tool?: string
    sessionID?: string
    sessionId?: string
  }
  output?: {
    args?: { command?: string }
    metadata?: Record<string, unknown>
  }
}

interface ToolAfterPayload {
  input?: {
    tool?: string
    sessionID?: string
    sessionId?: string
  }
  output?: {
    args?: { command?: string }
    output?: unknown
    metadata?: Record<string, unknown>
  }
  directory?: string
}

interface PendingCommandEntry {
  command: string
  categories: ValidationEvidenceCategory[]
}

interface SessionDeletedPayload {
  properties?: {
    info?: { id?: string }
  }
}

// Resolves stable session id across gateway payload variants.
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

function nextInvocationId(sessionIdValue: string, sequence: number): string {
  return `${sessionIdValue}:${sequence}`
}

function readInvocationId(payload: ToolBeforePayload | ToolAfterPayload): string {
  const value = payload.output?.metadata?.[VALIDATION_INVOCATION_ID_KEY]
  return typeof value === "string" ? value.trim() : ""
}

function readCommand(payload: ToolBeforePayload | ToolAfterPayload): string {
  return String(payload.output?.args?.command ?? "").trim()
}

function normalizeMetadata(metadata: unknown): Record<string, unknown> {
  return metadata && typeof metadata === "object" ? { ...(metadata as Record<string, unknown>) } : {}
}

// Returns true when command output indicates failure.
function commandFailed(output: string): boolean {
  const lower = output.toLowerCase()
  if (
    /npm err!|command failed|traceback|exception|cannot find|not found|elifecycle|exit code \d+/i.test(
      lower,
    )
  ) {
    return true
  }
  if (/\bfailed\b/i.test(lower) && !/\b(?:0\s+failed|failed\s*:\s*0|failures?\s*:\s*0)\b/i.test(lower)) {
    return true
  }
  return false
}

function outputText(output: unknown): string {
  if (typeof output === "string") {
    return output
  }
  if (!output || typeof output !== "object") {
    return ""
  }
  const record = output as Record<string, unknown>
  const parts = [record.stdout, record.stderr, record.output, record.message]
    .filter((item): item is string => typeof item === "string" && item.trim().length > 0)
    .map((item) => item.trim())
  return parts.join("\n")
}

function hasUsableOutput(output: unknown): boolean {
  if (typeof output === "string") {
    return true
  }
  if (!output || typeof output !== "object") {
    return false
  }
  const record = output as Record<string, unknown>
  if (typeof record.stdout === "string" && record.stdout.trim()) {
    return true
  }
  if (typeof record.stderr === "string" && record.stderr.trim()) {
    return true
  }
  if (typeof record.output === "string" && record.output.trim()) {
    return true
  }
  if (typeof record.message === "string" && record.message.trim()) {
    return true
  }
  return record.exitCode === 0 || record.ok === true || record.success === true
}

const VALIDATION_CATEGORY_BY_CHAR: Record<string, ValidationEvidenceCategory> = {
  L: "lint",
  T: "test",
  C: "typecheck",
  B: "build",
  S: "security",
}

function buildValidationInstruction(): string {
  return "Classify only the sanitized shell command for validation evidence. L=lint, T=test, C=typecheck, B=build, S=security, N=not_validation."
}

function normalizeValidationCommand(command: string): string {
  const trimmed = command.trim()
  return trimmed
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

// Creates validation evidence ledger hook to track successful validation commands.
export function createValidationEvidenceLedgerHook(options: {
  directory: string
  enabled: boolean
  decisionRuntime?: LlmDecisionRuntime
}): GatewayHook {
  const pendingCommandsByInvocation = new Map<string, PendingCommandEntry>()
  const invocationSequenceBySession = new Map<string, number>()
  const pendingInvocationIdsBySession = new Map<string, string[]>()
  return {
    id: "validation-evidence-ledger",
    priority: 330,
    async event(type: string, payload: unknown): Promise<void> {
      if (!options.enabled) {
        return
      }
      if (type === "session.deleted") {
        const eventPayload = (payload ?? {}) as SessionDeletedPayload
        const sid = sessionId(eventPayload)
        if (!sid) {
          return
        }
        invocationSequenceBySession.delete(sid)
        pendingInvocationIdsBySession.delete(sid)
        for (const key of pendingCommandsByInvocation.keys()) {
          if (key.startsWith(`${sid}:`)) {
            pendingCommandsByInvocation.delete(key)
          }
        }
        clearValidationEvidence(sid)
        return
      }
      if (type === "tool.execute.before") {
        const eventPayload = (payload ?? {}) as ToolBeforePayload
        const tool = String(eventPayload.input?.tool ?? "").toLowerCase()
        if (tool !== "bash") {
          return
        }
        const sid = sessionId(eventPayload)
        if (!sid) {
          return
        }
        const command = String(eventPayload.output?.args?.command ?? "").trim()
        if (!command) {
          return
        }
        const sequence = (invocationSequenceBySession.get(sid) ?? 0) + 1
        invocationSequenceBySession.set(sid, sequence)
        const invocationId = nextInvocationId(sid, sequence)
        const metadata = normalizeMetadata(eventPayload.output?.metadata)
        metadata[VALIDATION_INVOCATION_ID_KEY] = invocationId
        if (eventPayload.output) {
          eventPayload.output.metadata = metadata
        }
        pendingCommandsByInvocation.set(invocationId, {
          command,
          categories: classifyValidationCommand(command),
        })
        const queue = pendingInvocationIdsBySession.get(sid) ?? []
        queue.push(invocationId)
        pendingInvocationIdsBySession.set(sid, queue)
        return
      }
      if (type === "tool.execute.before.error") {
        const eventPayload = (payload ?? {}) as ToolAfterPayload
        const sid = sessionId(eventPayload)
        if (!sid) {
          return
        }
        const queue = pendingInvocationIdsBySession.get(sid) ?? []
        const command = readCommand(eventPayload)
        const byCommand = command
          ? queue.filter((candidate) => pendingCommandsByInvocation.get(candidate)?.command === command)
          : []
        const invocationId = readInvocationId(eventPayload) || byCommand[0] || (queue.length === 1 ? queue[0] : "")
        if (invocationId) {
          pendingCommandsByInvocation.delete(invocationId)
          const remaining = queue.filter((candidate) => candidate !== invocationId)
          if (remaining.length > 0) {
            pendingInvocationIdsBySession.set(sid, remaining)
          } else {
            pendingInvocationIdsBySession.delete(sid)
          }
        }
        return
      }
      if (type !== "tool.execute.after") {
        return
      }
      const eventPayload = (payload ?? {}) as ToolAfterPayload
      const tool = String(eventPayload.input?.tool ?? "").toLowerCase()
      if (tool !== "bash") {
        return
      }
      const sid = sessionId(eventPayload)
      if (!sid) {
        return
      }
      const queue = pendingInvocationIdsBySession.get(sid) ?? []
      const commandFromAfter = readCommand(eventPayload)
      const byCommand = commandFromAfter
        ? queue.filter((candidate) => pendingCommandsByInvocation.get(candidate)?.command === commandFromAfter)
        : []
      const invocationId = readInvocationId(eventPayload) || byCommand[0] || (queue.length === 1 ? queue[0] : "")
      if (!invocationId && queue.length > 1) {
        const directory =
          typeof eventPayload.directory === "string" && eventPayload.directory.trim()
            ? eventPayload.directory
            : options.directory
        writeGatewayEventAudit(directory, {
          hook: "validation-evidence-ledger",
          stage: "skip",
          reason_code: "validation_evidence_ambiguous_pending_commands",
          session_id: sid,
          pending_commands: queue.length,
        })
        for (const pendingId of queue) {
          pendingCommandsByInvocation.delete(pendingId)
        }
        pendingInvocationIdsBySession.delete(sid)
        return
      }
      const pending = invocationId ? pendingCommandsByInvocation.get(invocationId) : undefined
      if (invocationId) {
        pendingCommandsByInvocation.delete(invocationId)
        const remaining = queue.filter((candidate) => candidate !== invocationId)
        if (remaining.length > 0) {
          pendingInvocationIdsBySession.set(sid, remaining)
        } else {
          pendingInvocationIdsBySession.delete(sid)
        }
      }
      if (!pending?.command) {
        return
      }
      if (!hasUsableOutput(eventPayload.output?.output)) {
        return
      }
      const command = pending.command
      const output = outputText(eventPayload.output?.output)
      let categories = pending.categories
      if (categories.length === 0 && options.decisionRuntime) {
        const decision = await options.decisionRuntime.decide({
          hookId: "validation-evidence-ledger",
          sessionId: sid,
          templateId: "validation-command-classifier-v1",
          instruction: buildValidationInstruction(),
          context: buildValidationContext(command),
          allowedChars: ["L", "T", "C", "B", "S", "N"],
          decisionMeaning: {
            L: "lint",
            T: "test",
            C: "typecheck",
            B: "build",
            S: "security",
            N: "not_validation",
          },
          cacheKey: `validation-command:${command.trim().toLowerCase()}`,
        })
        if (decision.accepted) {
          const category = VALIDATION_CATEGORY_BY_CHAR[decision.char]
          if (category) {
            writeDecisionComparisonAudit({
              directory: options.directory,
              hookId: "validation-evidence-ledger",
              sessionId: sid,
              mode: options.decisionRuntime.config.mode,
              deterministicMeaning: "not_validation",
              aiMeaning: decision.meaning || category,
              deterministicValue: "none",
              aiValue: category,
            })
            writeGatewayEventAudit(options.directory, {
              hook: "validation-evidence-ledger",
              stage: "state",
              reason_code: "llm_validation_command_decision_recorded",
              session_id: sid,
              llm_decision_char: decision.char,
              llm_decision_meaning: decision.meaning,
              llm_decision_mode: options.decisionRuntime.config.mode,
              evidence: category,
            })
            if (options.decisionRuntime.config.mode === "shadow") {
              writeGatewayEventAudit(options.directory, {
                hook: "validation-evidence-ledger",
                stage: "state",
                reason_code: "llm_validation_command_shadow_deferred",
                session_id: sid,
                llm_decision_char: decision.char,
                llm_decision_meaning: decision.meaning,
                llm_decision_mode: options.decisionRuntime.config.mode,
                evidence: category,
              })
            } else {
              categories = [category]
            }
          }
        }
      }
      if (categories.length === 0) {
        return
      }
      if (commandFailed(output)) {
        return
      }
      const directory =
        typeof eventPayload.directory === "string" && eventPayload.directory.trim()
          ? eventPayload.directory
          : options.directory
      markValidationEvidence(sid, categories, directory)
      writeGatewayEventAudit(directory, {
        hook: "validation-evidence-ledger",
        stage: "state",
        reason_code: "validation_evidence_recorded",
        session_id: sid,
        evidence: categories.join(","),
      })
    },
  }
}

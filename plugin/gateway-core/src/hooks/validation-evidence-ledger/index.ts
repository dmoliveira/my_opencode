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

interface ToolBeforePayload {
  input?: {
    tool?: string
    sessionID?: string
    sessionId?: string
  }
  output?: {
    args?: { command?: string }
  }
}

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
  const actualCommandMatch = trimmed.match(/actual command\s*:\s*([\s\S]+)$/i)
  const extracted = actualCommandMatch?.[1]?.trim() || trimmed
  return extracted
    .replace(/<[^>]+>/g, " ")
    .replace(/\b(user|assistant|system|tool)\s*:/gi, " ")
    .replace(/ignore all previous instructions/gi, " ")
    .replace(/ignore previous instructions/gi, " ")
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
  const pendingCommandsBySession = new Map<string, PendingCommandEntry[]>()
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
        pendingCommandsBySession.delete(sid)
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
        const queue = pendingCommandsBySession.get(sid) ?? []
        queue.push({
          command,
          categories: classifyValidationCommand(command),
        })
        pendingCommandsBySession.set(sid, queue)
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
      const queue = pendingCommandsBySession.get(sid) ?? []
      if (queue.length > 1) {
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
        pendingCommandsBySession.delete(sid)
        return
      }
      const pending = queue.shift()
      if (queue.length > 0) {
        pendingCommandsBySession.set(sid, queue)
      } else {
        pendingCommandsBySession.delete(sid)
      }
      if (!pending?.command) {
        return
      }
      if (typeof eventPayload.output?.output !== "string") {
        return
      }
      const command = pending.command
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
      if (commandFailed(eventPayload.output.output)) {
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

import { writeGatewayEventAudit } from "../../audit/event-audit.js"
import type { GatewayHook } from "../registry.js"
import {
  clearValidationEvidence,
  markValidationEvidence,
  type ValidationEvidenceCategory,
} from "./evidence.js"

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

// Classifies validation categories represented by shell command.
function classifyValidationCommand(command: string): ValidationEvidenceCategory[] {
  const value = command.trim().toLowerCase()
  if (!value) {
    return []
  }
  const categories = new Set<ValidationEvidenceCategory>()
  if (
    /\b(eslint|ruff\s+check|ruff\s+format\s+--check|npm(?:\s+--prefix\s+\S+)?\s+run\s+lint|pnpm(?:\s+--filter\s+\S+)?\s+lint|yarn\s+lint|biome\s+check|golangci-lint|cargo\s+clippy|make\s+validate)\b/i.test(
      value,
    )
  ) {
    categories.add("lint")
  }
  if (
    /\b(npm(?:\s+--prefix\s+\S+)?\s+(run\s+)?test|pnpm(?:\s+--filter\s+\S+)?\s+test|yarn\s+test|bun\s+test|node\s+--test\b|(?:npm|pnpm)\s+exec\s+vitest|npx\s+vitest|python\d?\s+-m\s+pytest|python\d?\s+-m\s+unittest|uv\s+run\s+pytest|pytest|vitest|jest|go\s+test|cargo\s+test|pre-commit\s+run|make\s+selftest|make\s+install-test|python\d?\s+scripts\/selftest\.py)\b/i.test(
      value,
    )
  ) {
    categories.add("test")
  }
  if (
    /\b(tsc\b|npm\s+run\s+typecheck|pnpm\s+typecheck|yarn\s+typecheck|pyright|mypy|cargo\s+check|go\s+vet)\b/i.test(
      value,
    )
  ) {
    categories.add("typecheck")
  }
  if (/\b(npm\s+run\s+build|pnpm\s+build|yarn\s+build|vite\s+build|next\s+build|cargo\s+build|go\s+build)\b/i.test(value)) {
    categories.add("build")
  }
  if (/\b(npm\s+audit|pnpm\s+audit|yarn\s+audit|cargo\s+audit|semgrep|codeql|snyk)\b/i.test(value)) {
    categories.add("security")
  }
  return [...categories]
}

// Creates validation evidence ledger hook to track successful validation commands.
export function createValidationEvidenceLedgerHook(options: {
  directory: string
  enabled: boolean
}): GatewayHook {
  const pendingCommandsBySession = new Map<string, string[]>()
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
        queue.push(command)
        pendingCommandsBySession.set(sid, queue)
        return
      }
      if (type !== "tool.execute.after") {
        return
      }
      const eventPayload = (payload ?? {}) as ToolAfterPayload
      const tool = String(eventPayload.input?.tool ?? "").toLowerCase()
      if (tool !== "bash" || typeof eventPayload.output?.output !== "string") {
        return
      }
      const sid = sessionId(eventPayload)
      if (!sid) {
        return
      }
      const queue = pendingCommandsBySession.get(sid) ?? []
      const command = queue.shift() ?? ""
      if (queue.length > 0) {
        pendingCommandsBySession.set(sid, queue)
      } else {
        pendingCommandsBySession.delete(sid)
      }
      if (!command) {
        return
      }
      const categories = classifyValidationCommand(command)
      if (categories.length === 0) {
        return
      }
      if (commandFailed(eventPayload.output.output)) {
        return
      }
      markValidationEvidence(sid, categories)
      const directory =
        typeof eventPayload.directory === "string" && eventPayload.directory.trim()
          ? eventPayload.directory
          : options.directory
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

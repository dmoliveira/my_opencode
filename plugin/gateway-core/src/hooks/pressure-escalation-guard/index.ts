import { execSync } from "node:child_process"

import { writeGatewayEventAudit } from "../../audit/event-audit.js"
import type { GatewayHook } from "../registry.js"

interface ToolBeforePayload {
  input?: {
    tool?: string
    sessionID?: string
    sessionId?: string
  }
  output?: {
    args?: {
      subagent_type?: string
      prompt?: string
      description?: string
    }
  }
  directory?: string
}

function continueProcessCount(): number {
  const stdout = execSync("ps -axo command=", {
    encoding: "utf-8",
    stdio: ["ignore", "pipe", "ignore"],
    timeout: 1200,
  })
  let count = 0
  for (const rawLine of stdout.split("\n")) {
    const line = rawLine.trim().toLowerCase()
    if (!line) {
      continue
    }
    if (!/(^|[\s/])opencode(\s|$)/.test(line)) {
      continue
    }
    if (!line.includes("--continue")) {
      continue
    }
    count += 1
  }
  return count
}

function sessionId(payload: ToolBeforePayload): string {
  const value = payload.input?.sessionID ?? payload.input?.sessionId ?? ""
  return String(value).trim()
}

function includesAllowedPattern(text: string, patterns: string[]): boolean {
  const lower = text.toLowerCase()
  return patterns.some((pattern) => lower.includes(pattern.toLowerCase()))
}

// Blocks non-essential subagent escalations when continuation pressure is high.
export function createPressureEscalationGuardHook(options: {
  directory: string
  enabled: boolean
  maxContinueBeforeBlock: number
  blockedSubagentTypes: string[]
  allowPromptPatterns: string[]
  sampleContinueCount?: () => number
}): GatewayHook {
  return {
    id: "pressure-escalation-guard",
    priority: 318,
    async event(type: string, payload: unknown): Promise<void> {
      if (!options.enabled || type !== "tool.execute.before") {
        return
      }
      const eventPayload = (payload ?? {}) as ToolBeforePayload
      const directory =
        typeof eventPayload.directory === "string" && eventPayload.directory.trim()
          ? eventPayload.directory
          : options.directory
      const tool = String(eventPayload.input?.tool ?? "").toLowerCase()
      if (tool !== "task") {
        return
      }
      const subagentType = String(eventPayload.output?.args?.subagent_type ?? "").toLowerCase().trim()
      if (!subagentType || !options.blockedSubagentTypes.includes(subagentType)) {
        return
      }
      const prompt = String(eventPayload.output?.args?.prompt ?? "")
      const description = String(eventPayload.output?.args?.description ?? "")
      if (includesAllowedPattern(`${prompt}\n${description}`, options.allowPromptPatterns)) {
        writeGatewayEventAudit(directory, {
          hook: "pressure-escalation-guard",
          stage: "skip",
          reason_code: "pressure_escalation_override_allowed",
          session_id: sessionId(eventPayload),
          subagent_type: subagentType,
        })
        return
      }
      let continueCount = 0
      try {
        continueCount = options.sampleContinueCount ? options.sampleContinueCount() : continueProcessCount()
      } catch {
        writeGatewayEventAudit(directory, {
          hook: "pressure-escalation-guard",
          stage: "skip",
          reason_code: "pressure_escalation_sampling_failed",
          session_id: sessionId(eventPayload),
          subagent_type: subagentType,
        })
        return
      }
      if (continueCount < options.maxContinueBeforeBlock) {
        writeGatewayEventAudit(directory, {
          hook: "pressure-escalation-guard",
          stage: "skip",
          reason_code: "pressure_escalation_below_threshold",
          session_id: sessionId(eventPayload),
          subagent_type: subagentType,
          continue_count: continueCount,
        })
        return
      }
      writeGatewayEventAudit(directory, {
        hook: "pressure-escalation-guard",
        stage: "skip",
        reason_code: "pressure_escalation_blocked",
        session_id: sessionId(eventPayload),
        subagent_type: subagentType,
        continue_count: continueCount,
      })
      throw new Error(
        `Blocked ${subagentType} subagent escalation under high continuation pressure (${continueCount}). Finish active sessions or include a blocker/critical override in task prompt.`,
      )
    },
  }
}

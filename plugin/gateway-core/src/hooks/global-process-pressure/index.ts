import { execSync } from "node:child_process"

import { writeGatewayEventAudit } from "../../audit/event-audit.js"
import type { GatewayHook } from "../registry.js"
import type { StopContinuationGuard } from "../stop-continuation-guard/index.js"

interface ToolAfterPayload {
  input?: {
    sessionID?: string
    sessionId?: string
  }
  output?: {
    output?: unknown
  }
  directory?: string
}

interface SessionPressureState {
  lastWarnedAtToolCall: number
  lastCriticalWarnedAtToolCall: number
  lastSeenAtMs: number
}

interface PressureSample {
  opencodeProcessCount: number
  continueProcessCount: number
  maxRssMb: number
}

const CONTEXT_GUARD_PREFIX = "󰚩 Context Guard:"

function isOpencodeCommand(command: string): boolean {
  const lowered = command.trim().toLowerCase()
  if (!lowered) {
    return false
  }
  return /(^|[\s/])opencode(\s|$)/.test(lowered)
}

function resolveSessionId(payload: ToolAfterPayload): string {
  const candidates = [payload.input?.sessionID, payload.input?.sessionId]
  for (const value of candidates) {
    if (typeof value === "string" && value.trim()) {
      return value.trim()
    }
  }
  return ""
}

function guardPrefix(mode: "nerd" | "plain" | "both"): string {
  if (mode === "plain") {
    return "[Context Guard]:"
  }
  if (mode === "both") {
    return "󰚩 Context Guard [Context Guard]:"
  }
  return CONTEXT_GUARD_PREFIX
}

function pruneSessionStates(
  states: Map<string, SessionPressureState>,
  maxEntries: number,
): void {
  if (states.size <= maxEntries) {
    return
  }
  let oldestKey = ""
  let oldestAt = Number.POSITIVE_INFINITY
  for (const [key, state] of states.entries()) {
    if (state.lastSeenAtMs < oldestAt) {
      oldestAt = state.lastSeenAtMs
      oldestKey = key
    }
  }
  if (oldestKey) {
    states.delete(oldestKey)
  }
}

function sampleProcessPressure(): PressureSample {
  const stdout = execSync("ps -axo rss=,command=", {
    encoding: "utf-8",
    stdio: ["ignore", "pipe", "ignore"],
    timeout: 1200,
  })
  let opencodeProcessCount = 0
  let continueProcessCount = 0
  let maxRssMb = 0
  for (const rawLine of stdout.split("\n")) {
    const line = rawLine.trim()
    if (!line) {
      continue
    }
    const firstSpace = line.indexOf(" ")
    if (firstSpace <= 0) {
      continue
    }
    const rssToken = line.slice(0, firstSpace).trim()
    const command = line.slice(firstSpace + 1).trim().toLowerCase()
    if (!isOpencodeCommand(command)) {
      continue
    }
    opencodeProcessCount += 1
    if (command.includes("--continue")) {
      continueProcessCount += 1
    }
    const rssKb = Number.parseInt(rssToken, 10)
    if (Number.isFinite(rssKb) && rssKb > 0) {
      const rssMb = rssKb / 1024
      if (rssMb > maxRssMb) {
        maxRssMb = rssMb
      }
    }
  }
  return {
    opencodeProcessCount,
    continueProcessCount,
    maxRssMb,
  }
}

export function createGlobalProcessPressureHook(options: {
  directory: string
  stopGuard?: StopContinuationGuard
  enabled: boolean
  checkCooldownToolCalls: number
  reminderCooldownToolCalls: number
  criticalReminderCooldownToolCalls: number
  warningContinueSessions: number
  warningOpencodeProcesses: number
  warningMaxRssMb: number
  criticalMaxRssMb: number
  autoPauseOnCritical: boolean
  guardMarkerMode: "nerd" | "plain" | "both"
  guardVerbosity: "minimal" | "normal" | "debug"
  maxSessionStateEntries: number
  sampler?: () => PressureSample
}): GatewayHook {
  const sessionStates = new Map<string, SessionPressureState>()
  let globalToolCalls = 0
  let lastCheckedAtToolCall = 0
  let lastSample: PressureSample | null = null
  const runSample = options.sampler ?? sampleProcessPressure

  return {
    id: "global-process-pressure",
    priority: 275,
    async event(type: string, payload: unknown): Promise<void> {
      if (!options.enabled || type !== "tool.execute.after") {
        return
      }
      const eventPayload = (payload ?? {}) as ToolAfterPayload
      const directory =
        typeof eventPayload.directory === "string" && eventPayload.directory.trim()
          ? eventPayload.directory
          : options.directory
      const sessionId = resolveSessionId(eventPayload)
      if (!sessionId || typeof eventPayload.output?.output !== "string") {
        return
      }

      globalToolCalls += 1
      const priorState = sessionStates.get(sessionId) ?? {
        lastWarnedAtToolCall: 0,
        lastCriticalWarnedAtToolCall: 0,
        lastSeenAtMs: Date.now(),
      }
      const nextState: SessionPressureState = {
        ...priorState,
        lastSeenAtMs: Date.now(),
      }
      sessionStates.set(sessionId, nextState)
      pruneSessionStates(sessionStates, options.maxSessionStateEntries)

      const shouldSample =
        lastSample === null ||
        globalToolCalls - lastCheckedAtToolCall >= options.checkCooldownToolCalls
      if (shouldSample) {
        try {
          lastSample = runSample()
          lastCheckedAtToolCall = globalToolCalls
        } catch {
          writeGatewayEventAudit(directory, {
            hook: "global-process-pressure",
            stage: "skip",
            reason_code: "global_pressure_sample_failed",
            session_id: sessionId,
          })
          return
        }
      } else {
        writeGatewayEventAudit(directory, {
          hook: "global-process-pressure",
          stage: "skip",
          reason_code: "global_pressure_check_cooldown",
          session_id: sessionId,
        })
      }

      const sample = lastSample
      if (!sample) {
        return
      }
      const warningExceeded =
        sample.continueProcessCount >= options.warningContinueSessions ||
        sample.opencodeProcessCount >= options.warningOpencodeProcesses ||
        sample.maxRssMb >= options.warningMaxRssMb
      const criticalExceeded = sample.maxRssMb >= options.criticalMaxRssMb
      if (!warningExceeded && !criticalExceeded) {
        writeGatewayEventAudit(directory, {
          hook: "global-process-pressure",
          stage: "skip",
          reason_code: "global_pressure_below_threshold",
          session_id: sessionId,
        })
        return
      }
      const activeCooldownCalls = criticalExceeded
        ? options.criticalReminderCooldownToolCalls
        : options.reminderCooldownToolCalls
      const lastWarnedAt = criticalExceeded
        ? nextState.lastCriticalWarnedAtToolCall
        : nextState.lastWarnedAtToolCall
      if (lastWarnedAt > 0 && globalToolCalls - lastWarnedAt < activeCooldownCalls) {
        writeGatewayEventAudit(directory, {
          hook: "global-process-pressure",
          stage: "skip",
          reason_code: criticalExceeded
            ? "global_pressure_critical_cooldown"
            : "global_pressure_reminder_cooldown",
          session_id: sessionId,
        })
        return
      }

      const outputText = eventPayload.output.output
      const outputAppendAllowed =
        !outputText.includes("[ERROR]") &&
        !outputText.includes("[TOOL OUTPUT TRUNCATED]")

      const prefix = guardPrefix(options.guardMarkerMode)
      if (criticalExceeded) {
        if (outputAppendAllowed) {
          if (options.guardVerbosity === "minimal") {
            eventPayload.output.output = `${outputText}\n\n${prefix} Critical memory pressure detected.`
          } else if (options.guardVerbosity === "debug") {
            eventPayload.output.output = `${outputText}\n\n${prefix} Critical memory pressure detected.\n[continue_sessions=${sample.continueProcessCount}, opencode_processes=${sample.opencodeProcessCount}, max_rss_mb=${sample.maxRssMb.toFixed(1)}, critical_rss_mb=${options.criticalMaxRssMb}]`
          } else {
            eventPayload.output.output = `${outputText}\n\n${prefix} Critical memory pressure detected; continuation for this session is being auto-paused.`
          }
        }
        if (options.autoPauseOnCritical) {
          options.stopGuard?.forceStop(
            sessionId,
            "continuation_stopped_critical_memory_pressure",
          )
        }
        sessionStates.set(sessionId, {
          ...nextState,
          lastWarnedAtToolCall: globalToolCalls,
          lastCriticalWarnedAtToolCall: globalToolCalls,
        })
        writeGatewayEventAudit(directory, {
          hook: "global-process-pressure",
          stage: "state",
          reason_code: outputAppendAllowed
            ? "global_process_pressure_critical_appended"
            : "global_process_pressure_critical_detected_no_append",
          session_id: sessionId,
          continue_sessions: sample.continueProcessCount,
          opencode_processes: sample.opencodeProcessCount,
          max_rss_mb: Number(sample.maxRssMb.toFixed(1)),
          critical_rss_mb: options.criticalMaxRssMb,
          auto_pause: options.autoPauseOnCritical,
        })
        return
      }

      if (outputAppendAllowed) {
        if (options.guardVerbosity === "minimal") {
          eventPayload.output.output = `${outputText}\n\n${prefix} Global process pressure is high.`
        } else if (options.guardVerbosity === "debug") {
          eventPayload.output.output = `${outputText}\n\n${prefix} Global process pressure is high.\n[continue_sessions=${sample.continueProcessCount}, opencode_processes=${sample.opencodeProcessCount}, max_rss_mb=${sample.maxRssMb.toFixed(1)}]`
        } else {
          eventPayload.output.output = `${outputText}\n\n${prefix} Global process pressure is high; memory risk increases with many concurrent sessions.`
        }
      }
      sessionStates.set(sessionId, {
        ...nextState,
        lastWarnedAtToolCall: globalToolCalls,
      })
      writeGatewayEventAudit(directory, {
        hook: "global-process-pressure",
        stage: "state",
        reason_code: outputAppendAllowed
          ? "global_process_pressure_warning_appended"
          : "global_process_pressure_warning_detected_no_append",
        session_id: sessionId,
        continue_sessions: sample.continueProcessCount,
        opencode_processes: sample.opencodeProcessCount,
        max_rss_mb: Number(sample.maxRssMb.toFixed(1)),
      })
    },
  }
}

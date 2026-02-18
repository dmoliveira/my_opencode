import { execSync, spawnSync } from "node:child_process"

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
  criticalEventsInWindow: number
  criticalWindowStartToolCall: number
  lastSeenAtMs: number
}

interface SelfSessionPressureSample {
  pid: number
  cpuPct: number
  memPct: number
  rssMb: number
  elapsed: string
  elapsedSeconds: number
  cwd: string
}

interface PressureSample {
  opencodeProcessCount: number
  continueProcessCount: number
  maxRssMb: number
  selfSession: SelfSessionPressureSample | null
}

interface ProcessRow {
  pid: number
  ppid: number
  cpuPct: number
  memPct: number
  rssMb: number
  elapsed: string
  elapsedSeconds: number
  command: string
  commandLower: string
}

interface SelfPressureSummary {
  label: string
  isHigh: boolean
  operator: "any" | "all"
  cpuMatch: boolean
  rssMatch: boolean
  elapsedMatch: boolean
  elapsedThresholdSeconds: number
  sample: SelfSessionPressureSample | null
}

const CONTEXT_GUARD_PREFIX = "󰚩 Context Guard:"
const SESSION_PRESSURE_MARKER = "[SESSION-PRESSURE]"

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

function parseElapsedSeconds(raw: string): number {
  const value = raw.trim()
  if (!value) {
    return 0
  }
  let days = 0
  let clock = value
  if (value.includes("-")) {
    const parts = value.split("-", 2)
    days = Number.parseInt(parts[0] ?? "0", 10)
    clock = parts[1] ?? ""
  }
  const clockParts = clock.split(":").map((item) => Number.parseInt(item, 10))
  if (clockParts.some((item) => !Number.isFinite(item) || item < 0)) {
    return 0
  }
  let hours = 0
  let minutes = 0
  let seconds = 0
  if (clockParts.length === 3) {
    ;[hours, minutes, seconds] = clockParts
  } else if (clockParts.length === 2) {
    ;[minutes, seconds] = clockParts
  } else if (clockParts.length === 1) {
    ;[seconds] = clockParts
  }
  return days * 86_400 + hours * 3600 + minutes * 60 + seconds
}

function parseDurationThresholdSeconds(spec: string): number {
  const normalized = String(spec || "").trim().toLowerCase()
  const match = normalized.match(/^(\d+)\s*(s|sec|secs|second|seconds|m|min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days)$/)
  if (!match) {
    return 0
  }
  const value = Number.parseInt(match[1] ?? "0", 10)
  const unit = match[2] ?? "s"
  if (!Number.isFinite(value) || value <= 0) {
    return 0
  }
  if (["s", "sec", "secs", "second", "seconds"].includes(unit)) {
    return value
  }
  if (["m", "min", "mins", "minute", "minutes"].includes(unit)) {
    return value * 60
  }
  if (["h", "hr", "hrs", "hour", "hours"].includes(unit)) {
    return value * 3600
  }
  return value * 86_400
}

function readCwdForPid(pid: number): string {
  if (!Number.isFinite(pid) || pid <= 0) {
    return ""
  }
  try {
    const stdout = execSync(`lsof -a -p ${Math.floor(pid)} -d cwd -Fn`, {
      encoding: "utf-8",
      stdio: ["ignore", "pipe", "ignore"],
      timeout: 1200,
    })
    for (const line of stdout.split("\n")) {
      if (line.startsWith("n")) {
        return line.slice(1).trim()
      }
    }
  } catch {
    return ""
  }
  return ""
}

function parseProcessRows(stdout: string): ProcessRow[] {
  const rows: ProcessRow[] = []
  for (const rawLine of stdout.split("\n")) {
    const line = rawLine.trim()
    if (!line) {
      continue
    }
    const parts = line.split(/\s+/, 7)
    if (parts.length < 7) {
      continue
    }
    const pid = Number.parseInt(parts[0] ?? "0", 10)
    const ppid = Number.parseInt(parts[1] ?? "0", 10)
    const cpuPct = Number.parseFloat(parts[2] ?? "0")
    const memPct = Number.parseFloat(parts[3] ?? "0")
    const rssKb = Number.parseInt(parts[4] ?? "0", 10)
    const elapsed = String(parts[5] ?? "")
    const command = String(parts[6] ?? "").trim()
    if (!Number.isFinite(pid) || pid <= 0 || !command) {
      continue
    }
    rows.push({
      pid,
      ppid: Number.isFinite(ppid) && ppid > 0 ? ppid : 0,
      cpuPct: Number.isFinite(cpuPct) ? cpuPct : 0,
      memPct: Number.isFinite(memPct) ? memPct : 0,
      rssMb: Number.isFinite(rssKb) && rssKb > 0 ? rssKb / 1024 : 0,
      elapsed,
      elapsedSeconds: parseElapsedSeconds(elapsed),
      command,
      commandLower: command.toLowerCase(),
    })
  }
  return rows
}

function resolveSelfSessionSample(rows: ProcessRow[]): SelfSessionPressureSample | null {
  const rowByPid = new Map<number, ProcessRow>()
  for (const row of rows) {
    rowByPid.set(row.pid, row)
  }
  const visited = new Set<number>()
  let candidatePid = process.pid
  while (candidatePid > 1 && !visited.has(candidatePid)) {
    visited.add(candidatePid)
    const row = rowByPid.get(candidatePid)
    if (!row) {
      break
    }
    if (isOpencodeCommand(row.commandLower)) {
      return {
        pid: row.pid,
        cpuPct: row.cpuPct,
        memPct: row.memPct,
        rssMb: row.rssMb,
        elapsed: row.elapsed,
        elapsedSeconds: row.elapsedSeconds,
        cwd: readCwdForPid(row.pid),
      }
    }
    candidatePid = row.ppid
  }
  return null
}

function sampleProcessPressure(): PressureSample {
  const stdout = execSync("ps -axo pid=,ppid=,pcpu=,pmem=,rss=,etime=,command=", {
    encoding: "utf-8",
    stdio: ["ignore", "pipe", "ignore"],
    timeout: 1200,
  })
  const rows = parseProcessRows(stdout)
  let opencodeProcessCount = 0
  let continueProcessCount = 0
  let maxRssMb = 0
  for (const row of rows) {
    if (!isOpencodeCommand(row.commandLower)) {
      continue
    }
    opencodeProcessCount += 1
    if (row.commandLower.includes("--continue")) {
      continueProcessCount += 1
    }
    if (row.rssMb > maxRssMb) {
      maxRssMb = row.rssMb
    }
  }
  return {
    opencodeProcessCount,
    continueProcessCount,
    maxRssMb,
    selfSession: resolveSelfSessionSample(rows),
  }
}

function notifyCriticalPressure(message: string): boolean {
  if (process.platform === "darwin") {
    const script = `display notification ${JSON.stringify(message)} with title "OpenCode Context Guard"`
    const result = spawnSync("osascript", ["-e", script], {
      stdio: ["ignore", "ignore", "ignore"],
      timeout: 1000,
    })
    return result.status === 0
  }
  if (process.platform === "linux") {
    const result = spawnSync("notify-send", ["OpenCode Context Guard", message], {
      stdio: ["ignore", "ignore", "ignore"],
      timeout: 1000,
    })
    return result.status === 0
  }
  return false
}

function selfPressureSummary(
  sample: PressureSample,
  options: {
    operator: "any" | "all"
    highCpuPct: number
    highRssMb: number
    highElapsedSeconds: number
    highLabel: string
    lowLabel: string
  },
): SelfPressureSummary {
  const self = sample.selfSession
  const cpuMatch = !!self && options.highCpuPct > 0 && self.cpuPct >= options.highCpuPct
  const rssMatch = !!self && options.highRssMb > 0 && self.rssMb >= options.highRssMb
  const elapsedMatch =
    !!self && options.highElapsedSeconds > 0 && self.elapsedSeconds >= options.highElapsedSeconds
  const conditions = [
    options.highCpuPct > 0 ? cpuMatch : null,
    options.highRssMb > 0 ? rssMatch : null,
    options.highElapsedSeconds > 0 ? elapsedMatch : null,
  ].filter((item): item is boolean => item !== null)
  const isHigh =
    conditions.length > 0
      ? options.operator === "all"
        ? conditions.every(Boolean)
        : conditions.some(Boolean)
      : false
  return {
    label: isHigh ? options.highLabel : options.lowLabel,
    isHigh,
    operator: options.operator,
    cpuMatch,
    rssMatch,
    elapsedMatch,
    elapsedThresholdSeconds: options.highElapsedSeconds,
    sample: self,
  }
}

function appendSessionPressureMarker(output: string, summary: SelfPressureSummary): string {
  const details = [
    `${SESSION_PRESSURE_MARKER} PRESSURE=${summary.label}`,
    `pid=${summary.sample?.pid ?? "unknown"}`,
    `cpu_pct=${typeof summary.sample?.cpuPct === "number" ? summary.sample.cpuPct.toFixed(1) : "n/a"}`,
    `rss_mb=${typeof summary.sample?.rssMb === "number" ? summary.sample.rssMb.toFixed(1) : "n/a"}`,
    `elapsed=${summary.sample?.elapsed || "n/a"}`,
  ]
  if (summary.sample?.cwd) {
    details.push(`cwd=${summary.sample.cwd}`)
  }
  return `${output}\n${details.join(" ")}`
}

export function createGlobalProcessPressureHook(options: {
  directory: string
  stopGuard?: StopContinuationGuard
  enabled: boolean
  checkCooldownToolCalls: number
  reminderCooldownToolCalls: number
  criticalReminderCooldownToolCalls: number
  criticalEscalationWindowToolCalls: number
  criticalPauseAfterEvents: number
  criticalEscalationAfterEvents: number
  warningContinueSessions: number
  warningOpencodeProcesses: number
  warningMaxRssMb: number
  criticalMaxRssMb: number
  autoPauseOnCritical: boolean
  notifyOnCritical: boolean
  guardMarkerMode: "nerd" | "plain" | "both"
  guardVerbosity: "minimal" | "normal" | "debug"
  maxSessionStateEntries: number
  selfSeverityOperator?: "any" | "all"
  selfHighCpuPct?: number
  selfHighRssMb?: number
  selfHighElapsed?: string
  selfHighLabel?: string
  selfLowLabel?: string
  selfAppendMarker?: boolean
  sampler?: () => PressureSample
}): GatewayHook {
  const sessionStates = new Map<string, SessionPressureState>()
  let globalToolCalls = 0
  let lastCheckedAtToolCall = 0
  let lastSample: PressureSample | null = null
  const runSample = options.sampler ?? sampleProcessPressure
  const selfSeverityOperator = options.selfSeverityOperator === "all" ? "all" : "any"
  const selfHighCpuPct =
    typeof options.selfHighCpuPct === "number" && Number.isFinite(options.selfHighCpuPct)
      ? Math.max(0, options.selfHighCpuPct)
      : 100
  const selfHighRssMb =
    typeof options.selfHighRssMb === "number" && Number.isFinite(options.selfHighRssMb)
      ? Math.max(0, options.selfHighRssMb)
      : 10_240
  const selfHighElapsedSeconds = parseDurationThresholdSeconds(options.selfHighElapsed ?? "5h")
  const selfHighLabel =
    typeof options.selfHighLabel === "string" && options.selfHighLabel.trim()
      ? options.selfHighLabel.trim()
      : "HIGH"
  const selfLowLabel =
    typeof options.selfLowLabel === "string" && options.selfLowLabel.trim()
      ? options.selfLowLabel.trim()
      : "LOW"
  const selfAppendMarker = options.selfAppendMarker !== false

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
        criticalEventsInWindow: 0,
        criticalWindowStartToolCall: 0,
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
        return
      }

      const sample = lastSample
      if (!sample) {
        return
      }
      const selfSummary = selfPressureSummary(sample, {
        operator: selfSeverityOperator,
        highCpuPct: selfHighCpuPct,
        highRssMb: selfHighRssMb,
        highElapsedSeconds: selfHighElapsedSeconds,
        highLabel: selfHighLabel,
        lowLabel: selfLowLabel,
      })
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
          severity: selfSummary.label,
          self_pid: selfSummary.sample?.pid ?? null,
          self_cpu_pct: selfSummary.sample ? Number(selfSummary.sample.cpuPct.toFixed(1)) : null,
          self_rss_mb: selfSummary.sample ? Number(selfSummary.sample.rssMb.toFixed(1)) : null,
          self_elapsed_seconds: selfSummary.sample?.elapsedSeconds ?? null,
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
          severity: selfSummary.label,
          self_pid: selfSummary.sample?.pid ?? null,
        })
        return
      }

      const outputText = eventPayload.output.output
      const outputAppendAllowed =
        !outputText.includes("[ERROR]") &&
        !outputText.includes("[TOOL OUTPUT TRUNCATED]")

      const prefix = guardPrefix(options.guardMarkerMode)
      if (criticalExceeded) {
        const withinEscalationWindow =
          nextState.criticalWindowStartToolCall > 0 &&
          globalToolCalls - nextState.criticalWindowStartToolCall <=
            options.criticalEscalationWindowToolCalls
        const criticalEventsInWindow = withinEscalationWindow
          ? nextState.criticalEventsInWindow + 1
          : 1
        const criticalWindowStartToolCall = withinEscalationWindow
          ? nextState.criticalWindowStartToolCall
          : globalToolCalls
        const shouldEscalate =
          criticalEventsInWindow >= options.criticalEscalationAfterEvents
        const shouldPause =
          options.autoPauseOnCritical &&
          criticalEventsInWindow >= options.criticalPauseAfterEvents

        if (outputAppendAllowed) {
          if (options.guardVerbosity === "minimal") {
            eventPayload.output.output = `${outputText}\n\n${prefix} Critical memory pressure detected.`
          } else if (options.guardVerbosity === "debug") {
            eventPayload.output.output = `${outputText}\n\n${prefix} Critical memory pressure detected.\n[continue_sessions=${sample.continueProcessCount}, opencode_processes=${sample.opencodeProcessCount}, max_rss_mb=${sample.maxRssMb.toFixed(1)}, critical_rss_mb=${options.criticalMaxRssMb}, critical_events_in_window=${criticalEventsInWindow}]`
          } else {
            eventPayload.output.output = `${outputText}\n\n${prefix} Critical memory pressure detected${shouldEscalate ? " repeatedly" : ""}; ${shouldPause ? "continuation for this session is being auto-paused" : "continuation pause is armed if pressure repeats"}.`
          }
          if (selfAppendMarker) {
            eventPayload.output.output = appendSessionPressureMarker(String(eventPayload.output.output), selfSummary)
          }
        }
        if (shouldPause) {
          options.stopGuard?.forceStop(
            sessionId,
            "continuation_stopped_critical_memory_pressure",
          )
        }
        if (options.notifyOnCritical) {
          const notified = notifyCriticalPressure(
            `Critical memory pressure (${sample.maxRssMb.toFixed(1)} MB RSS) in session ${sessionId}`,
          )
          writeGatewayEventAudit(directory, {
            hook: "global-process-pressure",
            stage: "state",
            reason_code: notified
              ? "global_process_pressure_critical_notification_sent"
              : "global_process_pressure_critical_notification_failed",
            session_id: sessionId,
            severity: selfSummary.label,
            self_pid: selfSummary.sample?.pid ?? null,
          })
        }
        sessionStates.set(sessionId, {
          ...nextState,
          lastWarnedAtToolCall: globalToolCalls,
          lastCriticalWarnedAtToolCall: globalToolCalls,
          criticalEventsInWindow,
          criticalWindowStartToolCall,
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
          auto_pause: shouldPause,
          critical_events_in_window: criticalEventsInWindow,
          critical_escalated: shouldEscalate,
          severity: selfSummary.label,
          severity_operator: selfSummary.operator,
          self_pid: selfSummary.sample?.pid ?? null,
          self_cpu_pct: selfSummary.sample ? Number(selfSummary.sample.cpuPct.toFixed(1)) : null,
          self_mem_pct: selfSummary.sample ? Number(selfSummary.sample.memPct.toFixed(1)) : null,
          self_rss_mb: selfSummary.sample ? Number(selfSummary.sample.rssMb.toFixed(1)) : null,
          self_elapsed_seconds: selfSummary.sample?.elapsedSeconds ?? null,
          self_elapsed_raw: selfSummary.sample?.elapsed ?? null,
          self_cwd: selfSummary.sample?.cwd || null,
          self_high_cpu_match: selfSummary.cpuMatch,
          self_high_rss_match: selfSummary.rssMatch,
          self_high_elapsed_match: selfSummary.elapsedMatch,
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
        if (selfAppendMarker) {
          eventPayload.output.output = appendSessionPressureMarker(String(eventPayload.output.output), selfSummary)
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
        severity: selfSummary.label,
        severity_operator: selfSummary.operator,
        self_pid: selfSummary.sample?.pid ?? null,
        self_cpu_pct: selfSummary.sample ? Number(selfSummary.sample.cpuPct.toFixed(1)) : null,
        self_mem_pct: selfSummary.sample ? Number(selfSummary.sample.memPct.toFixed(1)) : null,
        self_rss_mb: selfSummary.sample ? Number(selfSummary.sample.rssMb.toFixed(1)) : null,
        self_elapsed_seconds: selfSummary.sample?.elapsedSeconds ?? null,
        self_elapsed_raw: selfSummary.sample?.elapsed ?? null,
        self_cwd: selfSummary.sample?.cwd || null,
        self_high_cpu_match: selfSummary.cpuMatch,
        self_high_rss_match: selfSummary.rssMatch,
        self_high_elapsed_match: selfSummary.elapsedMatch,
      })
    },
  }
}

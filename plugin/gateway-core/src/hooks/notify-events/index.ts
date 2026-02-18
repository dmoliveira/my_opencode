import { readFileSync } from "node:fs"
import { homedir } from "node:os"
import { join } from "node:path"
import { spawnSync } from "node:child_process"

import { writeGatewayEventAudit } from "../../audit/event-audit.js"
import type { GatewayHook } from "../registry.js"

type NotifyEvent = "complete" | "error" | "permission" | "question"

interface NotifyState {
  enabled: boolean
  sound: { enabled: boolean }
  visual: { enabled: boolean }
  events: Record<NotifyEvent, boolean>
  channels: Record<NotifyEvent, { sound: boolean; visual: boolean }>
}

interface EventPayload {
  input?: { tool?: string }
  properties?: Record<string, unknown>
  directory?: string
}

interface NotifyContent {
  title: string
  message: string
}

type NotifyStyle = "brief" | "detailed"

function defaultState(): NotifyState {
  return {
    enabled: true,
    sound: { enabled: true },
    visual: { enabled: true },
    events: {
      complete: true,
      error: true,
      permission: true,
      question: true,
    },
    channels: {
      complete: { sound: true, visual: true },
      error: { sound: true, visual: true },
      permission: { sound: true, visual: true },
      question: { sound: true, visual: true },
    },
  }
}

function toBool(value: unknown, fallback: boolean): boolean {
  return typeof value === "boolean" ? value : fallback
}

function parseState(raw: unknown): NotifyState {
  const source = raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {}
  const state = defaultState()
  state.enabled = toBool(source.enabled, state.enabled)
  if (source.sound && typeof source.sound === "object") {
    state.sound.enabled = toBool((source.sound as Record<string, unknown>).enabled, state.sound.enabled)
  }
  if (source.visual && typeof source.visual === "object") {
    state.visual.enabled = toBool((source.visual as Record<string, unknown>).enabled, state.visual.enabled)
  }
  if (source.events && typeof source.events === "object") {
    for (const key of Object.keys(state.events) as NotifyEvent[]) {
      state.events[key] = toBool((source.events as Record<string, unknown>)[key], state.events[key])
    }
  }
  if (source.channels && typeof source.channels === "object") {
    for (const key of Object.keys(state.channels) as NotifyEvent[]) {
      const channels = (source.channels as Record<string, unknown>)[key]
      if (!channels || typeof channels !== "object") {
        continue
      }
      state.channels[key].sound = toBool(
        (channels as Record<string, unknown>).sound,
        state.channels[key].sound,
      )
      state.channels[key].visual = toBool(
        (channels as Record<string, unknown>).visual,
        state.channels[key].visual,
      )
    }
  }
  return state
}

function readJson(path: string): unknown | null {
  try {
    return JSON.parse(readFileSync(path, "utf-8"))
  } catch {
    return null
  }
}

function loadNotifyState(directory: string): NotifyState {
  const legacyPath = process.env.OPENCODE_NOTIFICATIONS_PATH
  if (legacyPath) {
    const legacy = readJson(legacyPath)
    if (legacy) {
      return parseState(legacy)
    }
  }

  const globalConfigPath = join(homedir(), ".config", "opencode", "opencode.json")
  const globalConfig = readJson(globalConfigPath)
  if (globalConfig && typeof globalConfig === "object" && "notify" in (globalConfig as Record<string, unknown>)) {
    return parseState((globalConfig as Record<string, unknown>).notify)
  }

  const projectConfigPath = join(directory, "opencode.json")
  const projectConfig = readJson(projectConfigPath)
  if (projectConfig && typeof projectConfig === "object" && "notify" in (projectConfig as Record<string, unknown>)) {
    return parseState((projectConfig as Record<string, unknown>).notify)
  }

  return defaultState()
}

function eventFromType(type: string, payload: EventPayload): NotifyEvent | null {
  if (type === "session.idle") {
    return "complete"
  }
  if (type === "session.error") {
    return "error"
  }
  if (type.toLowerCase().includes("permission")) {
    return "permission"
  }
  if (type === "tool.execute.before") {
    const tool = String(payload.input?.tool || "").toLowerCase()
    if (tool === "question" || tool === "askuserquestion") {
      return "question"
    }
  }
  return null
}

function notifyVisual(title: string, message: string): boolean {
  if (process.platform === "darwin") {
    const script = `display notification ${JSON.stringify(message)} with title ${JSON.stringify(title)}`
    const result = spawnSync("osascript", ["-e", script], {
      stdio: ["ignore", "ignore", "ignore"],
      timeout: 1000,
    })
    return result.status === 0
  }
  if (process.platform === "linux") {
    const result = spawnSync("notify-send", [title, message], {
      stdio: ["ignore", "ignore", "ignore"],
      timeout: 1000,
    })
    return result.status === 0
  }
  return false
}

function notifySound(): boolean {
  try {
    process.stderr.write("\u0007")
    return true
  } catch {
    return false
  }
}

function cleanText(value: unknown): string {
  if (typeof value !== "string") {
    return ""
  }
  return value.replace(/\s+/g, " ").trim()
}

function truncateText(value: string, maxChars: number): string {
  if (value.length <= maxChars) {
    return value
  }
  if (maxChars <= 3) {
    return value.slice(0, maxChars)
  }
  return `${value.slice(0, maxChars - 3).trimEnd()}...`
}

function firstPropertyText(properties: Record<string, unknown>, keys: string[]): string {
  for (const key of keys) {
    const value = cleanText(properties[key])
    if (value) {
      return value
    }
  }
  return ""
}

function messageForEvent(eventName: NotifyEvent, payload: EventPayload, style: NotifyStyle): NotifyContent {
  const properties = payload.properties && typeof payload.properties === "object" ? payload.properties : {}
  if (eventName === "complete") {
    return {
      title: "OpenCode Complete",
      message: style === "detailed" ? "Task completed successfully." : "Task completed.",
    }
  }
  if (eventName === "error") {
    const detail = truncateText(
      firstPropertyText(properties, ["message", "error", "reason", "detail"]),
      style === "detailed" ? 180 : 120,
    )
    return {
      title: "OpenCode Error",
      message: detail
        ? style === "detailed"
          ? `Session error detected: ${detail}`
          : `Session error: ${detail}`
        : "Session error detected.",
    }
  }
  if (eventName === "permission") {
    const detail = truncateText(
      firstPropertyText(properties, ["permission", "action", "command", "tool"]),
      style === "detailed" ? 140 : 100,
    )
    return {
      title: "OpenCode Permission",
      message: detail
        ? style === "detailed"
          ? `Action required before continuing: ${detail}`
          : `Permission required: ${detail}`
        : "Permission prompt requires input.",
    }
  }
  const question = truncateText(
    firstPropertyText(properties, ["question", "prompt", "title", "label"]),
    style === "detailed" ? 140 : 100,
  )
  return {
    title: "OpenCode Input Needed",
    message: question
      ? style === "detailed"
        ? `Response needed to continue: ${question}`
        : `Question: ${question}`
      : "Question requires input.",
  }
}

export function createNotifyEventsHook(options: {
  directory: string
  enabled: boolean
  cooldownMs: number
  style: NotifyStyle
  now?: () => number
  loadState?: (directory: string) => NotifyState
  notify?: (eventName: NotifyEvent, visual: boolean, sound: boolean, content: NotifyContent) => {
    visualSent: boolean
    soundSent: boolean
  }
}): GatewayHook {
  const lastSent = new Map<NotifyEvent, number>()
  const now = options.now ?? (() : number => Date.now())
  const loadStateFn = options.loadState ?? loadNotifyState
  const notifyFn =
    options.notify ??
    ((_eventName: NotifyEvent, visual: boolean, sound: boolean, content: NotifyContent): {
      visualSent: boolean
      soundSent: boolean
    } => ({
      visualSent: visual ? notifyVisual(content.title, content.message) : false,
      soundSent: sound ? notifySound() : false,
    }))

  return {
    id: "notify-events",
    priority: 175,
    async event(type: string, payload: unknown): Promise<void> {
      if (!options.enabled) {
        return
      }
      const eventPayload = (payload ?? {}) as EventPayload
      const directory =
        typeof eventPayload.directory === "string" && eventPayload.directory.trim()
          ? eventPayload.directory
          : options.directory
      const eventName = eventFromType(type, eventPayload)
      if (!eventName) {
        return
      }
      const state = loadStateFn(directory)
      if (!state.enabled || !state.events[eventName]) {
        return
      }

      const visual = state.visual.enabled && state.channels[eventName].visual
      const sound = state.sound.enabled && state.channels[eventName].sound
      if (!visual && !sound) {
        return
      }

      const ts = now()
      const previous = lastSent.get(eventName) ?? 0
      if (options.cooldownMs > 0 && previous > 0 && ts - previous < options.cooldownMs) {
        writeGatewayEventAudit(directory, {
          hook: "notify-events",
          stage: "skip",
          reason_code: "cooldown_active",
          event_type: type,
          notify_event: eventName,
          cooldown_ms: options.cooldownMs,
        })
        return
      }

      const content = messageForEvent(eventName, eventPayload, options.style)
      const result = notifyFn(eventName, visual, sound, content)
      lastSent.set(eventName, ts)
      writeGatewayEventAudit(directory, {
        hook: "notify-events",
        stage: "state",
        reason_code: result.visualSent || result.soundSent ? "notification_sent" : "notification_not_sent",
        event_type: type,
        notify_event: eventName,
        visual_enabled: visual,
        sound_enabled: sound,
        visual_sent: result.visualSent,
        sound_sent: result.soundSent,
      })
    },
  }
}

import { writeGatewayEventAudit } from "../../audit/event-audit.js"
import type { GatewayHook } from "../registry.js"

interface ToolBeforePayload {
  input?: {
    tool?: string
    sessionID?: string
    sessionId?: string
  }
  output?: {
    args?: { command?: string }
  }
  directory?: string
}

function shouldPrefixCommand(command: string, prefixes: string[]): boolean {
  const binary = commandBinary(command)
  if (!binary) {
    return false
  }
  return prefixes.some((prefix) => binary === prefix.toLowerCase())
}

function envKey(entry: string): string {
  return entry.split("=", 1)[0]?.trim() ?? ""
}

function hasEnvAssignment(command: string, key: string): boolean {
  return new RegExp(`(^|\\s)${key}=`, "i").test(command.trim())
}

function commandBinary(command: string): string {
  const tokens = command.trim().split(/\s+/).filter(Boolean)
  for (const token of tokens) {
    if (/^[A-Za-z_][A-Za-z0-9_]*=/.test(token)) {
      continue
    }
    return token.toLowerCase()
  }
  return ""
}

function allowedEnvKeys(command: string): Set<string> {
  const binary = commandBinary(command)
  if (binary === "git" || binary === "gh") {
    return new Set(["CI", "GIT_TERMINAL_PROMPT", "GIT_EDITOR", "GIT_PAGER", "PAGER", "GCM_INTERACTIVE", "OPENCODE_SESSION_ID"])
  }
  return new Set()
}

function shellQuoteEnvValue(value: string): string {
  return `'${value.replace(/'/g, `'"'"'`)}'`
}

function sessionEnvPrefixes(sessionId: string): string[] {
  const normalized = sessionId.trim()
  if (!normalized) {
    return []
  }
  return [`OPENCODE_SESSION_ID=${shellQuoteEnvValue(normalized)}`]
}

function prefixCommand(command: string, envPrefixes: string[]): string {
  const allowlist = allowedEnvKeys(command)
  const assignments = envPrefixes
    .map((item) => item.trim())
    .filter(Boolean)
    .filter((entry) => {
      if (allowlist.size === 0) {
        return true
      }
      const key = envKey(entry)
      return key ? allowlist.has(key) : false
    })
    .filter((entry) => {
      const key = envKey(entry)
      if (!key) {
        return false
      }
      return !hasEnvAssignment(command, key)
    })
  if (assignments.length === 0) {
    return command
  }
  return `${assignments.join(" ")} ${command.trim()}`.trim()
}

// Returns first non-interactive violation message for command.
function violation(command: string, blockedPatterns: RegExp[]): string | null {
  const value = command.trim()
  if (!value) {
    return null
  }
  for (const pattern of blockedPatterns) {
    if (pattern.test(value)) {
      return "Interactive command detected. Use non-interactive flags or scripted command execution."
    }
  }
  const lower = value.toLowerCase()
  if (/\bnpm\s+install\b/.test(lower) && !/--yes\b/.test(lower)) {
    return "Use `npm install --yes` in non-interactive sessions."
  }
  if (/\byarn\s+install\b/.test(lower) && !/--non-interactive\b/.test(lower)) {
    return "Use `yarn install --non-interactive` in non-interactive sessions."
  }
  if (/\bpnpm\s+install\b/.test(lower) && !/--reporter\s*=\s*silent\b/.test(lower)) {
    return "Use `pnpm install --reporter=silent` in non-interactive sessions."
  }
  if (/\bapt(-get)?\s+install\b/.test(lower) && !/\s-y\b/.test(lower)) {
    return "Use apt install commands with `-y` in non-interactive sessions."
  }
  if (/^\s*(python3?|node)\s*$/.test(lower)) {
    return "REPL command detected. Use script mode (`python -c`, `node -e`, or file execution)."
  }
  if (/\bgit\s+commit\b/.test(lower) && !/\s-m\s+/.test(lower)) {
    return "Use non-interactive git commit format: `git commit -m \"message\"`."
  }
  return null
}

// Creates non-interactive shell guard for prompt-prone command patterns.
export function createNoninteractiveShellGuardHook(options: {
  directory: string
  enabled: boolean
  injectEnvPrefix: boolean
  envPrefixes: string[]
  prefixCommands: string[]
  blockedPatterns: string[]
}): GatewayHook {
  const blockedPatterns = options.blockedPatterns
    .map((pattern) => {
      try {
        return new RegExp(pattern, "i")
      } catch {
        return null
      }
    })
    .filter((value): value is RegExp => value !== null)
  return {
    id: "noninteractive-shell-guard",
    priority: 385,
    async event(type: string, payload: unknown): Promise<void> {
      if (!options.enabled || type !== "tool.execute.before") {
        return
      }
      const eventPayload = (payload ?? {}) as ToolBeforePayload
      const tool = String(eventPayload.input?.tool ?? "").toLowerCase()
      if (tool !== "bash") {
        return
      }
      const command = String(eventPayload.output?.args?.command ?? "").trim()
      if (!command) {
        return
      }
      const sessionId = String(eventPayload.input?.sessionID ?? eventPayload.input?.sessionId ?? "")
      const directory =
        typeof eventPayload.directory === "string" && eventPayload.directory.trim()
          ? eventPayload.directory
          : options.directory

      const sessionPrefixed = prefixCommand(command, sessionEnvPrefixes(sessionId))
      if (sessionPrefixed !== command && eventPayload.output?.args) {
        eventPayload.output.args.command = sessionPrefixed
        writeGatewayEventAudit(directory, {
          hook: "noninteractive-shell-guard",
          stage: "state",
          reason_code: "runtime_session_env_prefixed",
          session_id: sessionId,
        })
      }

      const commandWithSessionEnv = String(eventPayload.output?.args?.command ?? command).trim()
      if (
        options.injectEnvPrefix &&
        shouldPrefixCommand(command, options.prefixCommands)
      ) {
        const prefixed = prefixCommand(commandWithSessionEnv, options.envPrefixes)
        if (prefixed !== commandWithSessionEnv && eventPayload.output?.args) {
          eventPayload.output.args.command = prefixed
          writeGatewayEventAudit(directory, {
            hook: "noninteractive-shell-guard",
            stage: "state",
            reason_code: "noninteractive_env_prefixed",
            session_id: sessionId,
          })
        }
      }

      const updatedCommand = String(eventPayload.output?.args?.command ?? commandWithSessionEnv).trim()
      const message = violation(updatedCommand, blockedPatterns)
      if (!message) {
        return
      }
      writeGatewayEventAudit(directory, {
        hook: "noninteractive-shell-guard",
        stage: "skip",
        reason_code: "interactive_command_blocked",
        session_id: sessionId,
      })
      throw new Error(`[noninteractive-shell-guard] ${message}`)
    },
  }
}

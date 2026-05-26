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

interface ParsedCommand {
  binary: string
  args: string[]
}

function interactiveRemediationHint(command: string): string {
  const lower = command.trim().toLowerCase()
  const parsed = parseCommand(command)
  const binary = baseCommandName(parsed.binary)
  const argsLower = parsed.args.map((item) => item.toLowerCase())
  if (/\bgit\s+add\s+-p\b/.test(lower)) {
    return "Use `git add <path>` or `git add .` instead of patch mode."
  }
  if (/\bgit\s+rebase\s+-i\b/.test(lower)) {
    return "Use non-interactive `git rebase` flows, or perform the interactive rebase manually outside gateway automation."
  }
  if (/\b(vim|vi|nano|emacs)\b/.test(lower)) {
    return "Use file-edit tools or scripted file writes instead of launching an editor."
  }
  if (/\b(less|more|man)\b/.test(lower)) {
    return "Use `--help`, targeted file reads, or `git --no-pager ...` style commands instead of pagers/manual pages."
  }
  if (/\bnpm\s+install\b/.test(lower) && !/--yes\b/.test(lower)) {
    return "Use `npm install --yes`."
  }
  if (/\byarn\s+install\b/.test(lower) && !/--non-interactive\b/.test(lower)) {
    return "Use `yarn install --non-interactive`."
  }
  if (/\bpnpm\s+install\b/.test(lower) && !/--reporter\s*=\s*silent\b/.test(lower)) {
    return "Use `pnpm install --reporter=silent`."
  }
  if (/\bapt(?:-get)?\s+install\b/.test(lower) && !/\s-y\b/.test(lower)) {
    return "Use apt install commands with `-y`."
  }
  if (binary === "gh" && argsLower[1] === "pr" && argsLower[2] === "create") {
    if (hasAnyFlag(argsLower, ["--web", "-w", "--editor", "-e"])) {
      return "Use scripted `gh pr create` flags like `--title`, `--body-file`, or `--fill-verbose` instead of browser/editor flows."
    }
    return "Use non-interactive `gh pr create --title \"...\" --body-file <path>` or `gh pr create --fill-verbose`."
  }
  if (/^\s*(python3?|node)\s*$/.test(lower)) {
    return "Use script mode like `python -c`, `node -e`, or a file path instead of a REPL."
  }
  if (binary === "git" && argsLower[1] === "commit" && !argsLower.some((item) => item === "-m" || item.startsWith("-m"))) {
    return 'Use `git commit -m "message"`.'
  }
  return "Use non-interactive flags or scripted command execution."
}

function baseCommandName(binary: string): string {
  const normalized = binary.trim().toLowerCase()
  if (!normalized) {
    return ""
  }
  const parts = normalized.split("/")
  return parts[parts.length - 1] ?? normalized
}

function tokenizeShellWords(command: string): string[] {
  const tokens: string[] = []
  let current = ""
  let quote: '"' | "'" | null = null

  for (let index = 0; index < command.length; index += 1) {
    const char = command[index] ?? ""
    if (quote) {
      if (char === quote) {
        quote = null
      } else if (char === "\\" && quote === '"' && index + 1 < command.length) {
        current += command[index + 1] ?? ""
        index += 1
      } else {
        current += char
      }
      continue
    }
    if (char === '"' || char === "'") {
      quote = char
      continue
    }
    if (/\s/.test(char)) {
      if (current) {
        tokens.push(current)
        current = ""
      }
      continue
    }
    if (char === "\\" && index + 1 < command.length) {
      current += command[index + 1] ?? ""
      index += 1
      continue
    }
    current += char
  }

  if (current) {
    tokens.push(current)
  }
  return tokens
}

function stripQuotedText(command: string): string {
  let result = ""
  let quote: '"' | "'" | null = null
  for (let index = 0; index < command.length; index += 1) {
    const char = command[index] ?? ""
    if (quote) {
      if (char === quote) {
        quote = null
      } else if (char === "\\" && quote === '"' && index + 1 < command.length) {
        index += 1
      }
      continue
    }
    if (char === '"' || char === "'") {
      quote = char
      continue
    }
    result += char
  }
  return result
}

function sanitizeBlockedPatternTarget(command: string): string {
  const stripped = stripQuotedText(command)
  const tokens = tokenizeShellWords(stripped)
  const sanitized: string[] = []
  const valueFlags = new Set(["-m", "--message", "-t", "--title", "-b", "--body", "-f", "--body-file"])
  for (let index = 0; index < tokens.length; index += 1) {
    const token = tokens[index] ?? ""
    const lower = token.toLowerCase()
    if (valueFlags.has(lower)) {
      sanitized.push(token)
      if (index + 1 < tokens.length) {
        sanitized.push("<value>")
        index += 1
      }
      continue
    }
    const equalIndex = token.indexOf("=")
    if (equalIndex > 0 && valueFlags.has(token.slice(0, equalIndex).toLowerCase())) {
      sanitized.push(`${token.slice(0, equalIndex)}=<value>`)
      continue
    }
    sanitized.push(token)
  }
  return sanitized.join(" ")
}

function shouldPrefixCommand(command: string, prefixes: string[]): boolean {
  const binary = baseCommandName(parseCommand(command).binary)
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
  return baseCommandName(parseCommand(command).binary)
}

function parseCommand(command: string): ParsedCommand {
  const tokens = tokenizeShellWords(command.trim())
  let index = 0
  while (index < tokens.length && /^[A-Za-z_][A-Za-z0-9_]*=/.test(tokens[index] ?? "")) {
    index += 1
  }
  if ((tokens[index] ?? "").toLowerCase() === "env") {
    index += 1
    while (index < tokens.length && /^[A-Za-z_][A-Za-z0-9_]*=/.test(tokens[index] ?? "")) {
      index += 1
    }
  }
  const filtered = tokens.slice(index)
  if (filtered.length === 0) {
    return { binary: "", args: [] }
  }
  const [first, second, ...rest] = filtered
  const normalizedFirst = first?.toLowerCase() ?? ""
  if (normalizedFirst.endsWith("/rtk") || normalizedFirst === "rtk") {
    const wrappedBinary = second?.toLowerCase() ?? ""
    return {
      binary: wrappedBinary,
      args: second ? [second, ...rest] : [],
    }
  }
  return {
    binary: normalizedFirst,
    args: [first, second, ...rest].filter((item): item is string => Boolean(item)),
  }
}

function allowedEnvKeys(command: string): Set<string> {
  const binary = commandBinary(command)
  if (binary === "git") {
    return new Set(["CI", "GIT_TERMINAL_PROMPT", "GIT_EDITOR", "GIT_PAGER", "PAGER", "GCM_INTERACTIVE", "OPENCODE_SESSION_ID"])
  }
  if (binary === "gh") {
    return new Set([
      "CI",
      "GIT_TERMINAL_PROMPT",
      "GIT_EDITOR",
      "GIT_PAGER",
      "PAGER",
      "GCM_INTERACTIVE",
      "GH_PROMPT_DISABLED",
      "GH_EDITOR",
      "BROWSER",
      "OPENCODE_SESSION_ID",
    ])
  }
  return new Set()
}

function hasAnyFlag(argsLower: string[], flags: string[]): boolean {
  return argsLower.some((item) => flags.includes(item))
}

function hasValueFlag(argsLower: string[], longFlag: string, shortFlag: string): boolean {
  return argsLower.some(
    (item, index) =>
      item === longFlag ||
      item.startsWith(`${longFlag}=`) ||
      item === shortFlag ||
      item.startsWith(shortFlag) ||
      argsLower[index - 1] === longFlag ||
      argsLower[index - 1] === shortFlag,
  )
}

function isScriptedGhPrCreate(binary: string, argsLower: string[]): boolean {
  if (binary !== "gh" || argsLower[1] !== "pr" || argsLower[2] !== "create") {
    return false
  }
  const hasFill = hasAnyFlag(argsLower, ["--fill", "--fill-first", "--fill-verbose"])
  const hasTitle = hasValueFlag(argsLower, "--title", "-t")
  const hasBody = hasValueFlag(argsLower, "--body", "-b") || hasValueFlag(argsLower, "--body-file", "-f")
  return (hasFill || hasTitle) && (hasFill || hasBody)
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
  const blockedPatternTarget = sanitizeBlockedPatternTarget(value)
  for (const pattern of blockedPatterns) {
    if (pattern.test(blockedPatternTarget)) {
      return "Interactive command detected. Use non-interactive flags or scripted command execution."
    }
  }
  const lower = value.toLowerCase()
  const parsed = parseCommand(value)
  const binary = baseCommandName(parsed.binary)
  const argsLower = parsed.args.map((item) => item.toLowerCase())
  if (binary === "gh" && argsLower[1] === "pr" && argsLower[2] === "create") {
    if (hasAnyFlag(argsLower, ["--web", "-w", "--editor", "-e"])) {
      return "Use scripted `gh pr create` flags like `--title`, `--body-file`, or `--fill-verbose` in non-interactive sessions, not browser/editor flows."
    }
    if (!isScriptedGhPrCreate(binary, argsLower)) {
      return "Use non-interactive gh PR creation format: `gh pr create --title \"...\" --body \"...\"` (or `--body-file` / `--fill`)."
    }
    return null
  }
  if (binary === "npm" && /\bnpm\s+install\b/.test(lower) && !/--yes\b/.test(lower)) {
    return "Use `npm install --yes` in non-interactive sessions."
  }
  if (binary === "yarn" && /\byarn\s+install\b/.test(lower) && !/--non-interactive\b/.test(lower)) {
    return "Use `yarn install --non-interactive` in non-interactive sessions."
  }
  if (binary === "pnpm" && /\bpnpm\s+install\b/.test(lower) && !/--reporter\s*=\s*silent\b/.test(lower)) {
    return "Use `pnpm install --reporter=silent` in non-interactive sessions."
  }
  if ((binary === "apt" || binary === "apt-get") && /\bapt(-get)?\s+install\b/.test(lower) && !/\s-y\b/.test(lower)) {
    return "Use apt install commands with `-y` in non-interactive sessions."
  }
  if (binary === "python" || binary === "python3" || binary === "node") {
    if (parsed.args.length <= 1) {
      return "REPL command detected. Use script mode (`python -c`, `node -e`, or file execution)."
    }
  }
  if (/^\s*(python3?|node)\s*$/.test(lower)) {
    return "REPL command detected. Use script mode (`python -c`, `node -e`, or file execution)."
  }
  if (binary === "git" && argsLower[1] === "commit") {
    if (!argsLower.some((item, index) => item === "-m" || item.startsWith("-m") || argsLower[index - 1] === "-m")) {
      return "Use non-interactive git commit format: `git commit -m \"message\"`."
    }
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
        blocked_command: updatedCommand,
      })
      const hint = interactiveRemediationHint(updatedCommand)
      throw new Error(`[noninteractive-shell-guard] ${message} Blocked command: ${updatedCommand}. ${hint}`)
    },
  }
}

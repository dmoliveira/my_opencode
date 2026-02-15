// Parses a slash command name and argument suffix.
export function parseSlashCommand(raw: string): { name: string; args: string } {
  const trimmed = raw.trim().replace(/^\//, "")
  if (!trimmed) {
    return { name: "", args: "" }
  }
  const [name, ...tail] = trimmed.split(/\s+/)
  return {
    name: name.toLowerCase(),
    args: tail.join(" ").trim(),
  }
}

// Parses rendered autopilot command-template invocations into logical command semantics.
export function parseAutopilotTemplateCommand(raw: string): { name: string; args: string } | null {
  const trimmed = raw.trim()
  if (!trimmed || !/autopilot_command\.py/i.test(trimmed)) {
    return null
  }
  const match = trimmed.match(/autopilot_command\.py["']?\s+([a-z-]+)(.*)$/i)
  if (!match) {
    return null
  }
  const subcommand = String(match[1] || "").trim().toLowerCase()
  const args = String(match[2] || "").trim()
  const map: Record<string, string> = {
    go: "autopilot-go",
    start: "autopilot",
    resume: "autopilot-resume",
    pause: "autopilot-pause",
    stop: "autopilot-stop",
  }
  const name = map[subcommand]
  if (!name) {
    return null
  }
  return { name, args }
}

const AUTOPILOT_START_COMMANDS = new Set([
  "autopilot",
  "autopilot-go",
  "autopilot-resume",
  "continue-work",
  "autopilot-objective",
])

const AUTOPILOT_STOP_COMMANDS = new Set(["autopilot-stop", "autopilot-pause"])

const AUTOPILOT_COMPAT_START_ALIASES = new Set(["ralph-loop"])

const AUTOPILOT_COMPAT_STOP_ALIASES = new Set(["cancel-ralph"])

// Normalizes compatibility aliases to canonical autopilot command names.
export function canonicalAutopilotCommandName(name: string): string {
  if (AUTOPILOT_COMPAT_START_ALIASES.has(name)) {
    return "autopilot-go"
  }
  if (AUTOPILOT_COMPAT_STOP_ALIASES.has(name)) {
    return "autopilot-stop"
  }
  return name
}

// Resolves action semantics for autopilot command names and argument forms.
export function resolveAutopilotAction(name: string, args: string): "start" | "stop" | "none" {
  const command = canonicalAutopilotCommandName(name)
  if (isAutopilotStopCommand(command)) {
    return "stop"
  }
  if (!isAutopilotCommand(command)) {
    return "none"
  }
  if (command === "autopilot") {
    const head = args.trim().split(/\s+/)[0]?.toLowerCase() ?? ""
    if (head === "stop" || head === "pause") {
      return "stop"
    }
  }
  return "start"
}

// Returns true when command should start or continue autopilot loop.
export function isAutopilotCommand(name: string): boolean {
  return AUTOPILOT_START_COMMANDS.has(name) || AUTOPILOT_COMPAT_START_ALIASES.has(name)
}

// Returns true when command should stop active autopilot loop.
export function isAutopilotStopCommand(name: string): boolean {
  return AUTOPILOT_STOP_COMMANDS.has(name) || AUTOPILOT_COMPAT_STOP_ALIASES.has(name)
}

// Parses completion mode from command argument string.
export function parseCompletionMode(args: string): "promise" | "objective" {
  const explicit = args.match(/--completion-mode\s+(promise|objective)/i)
  if (explicit?.[1]?.toLowerCase() === "objective") {
    return "objective"
  }
  return "promise"
}

// Parses completion promise token from command argument string.
export function parseCompletionPromise(args: string, fallback: string): string {
  const quoted = args.match(/--completion-promise\s+"([^"]+)"/i)
  if (quoted?.[1]?.trim()) {
    return quoted[1].trim()
  }
  const plain = args.match(/--completion-promise\s+([^\s]+)/i)
  if (plain?.[1]?.trim()) {
    return plain[1].trim()
  }
  return fallback
}

// Parses iteration cap from command argument string.
export function parseMaxIterations(args: string, fallback: number): number {
  const match = args.match(/--max-iterations\s+(\d+)/i)
  if (!match) {
    return fallback
  }
  const parsed = Number.parseInt(match[1], 10)
  if (!Number.isFinite(parsed) || parsed < 0) {
    return fallback
  }
  return parsed
}

// Parses goal text from command argument string.
export function parseGoal(args: string): string {
  const goal = args.match(/--goal\s+"([^"]+)"/i)
  if (goal?.[1]?.trim()) {
    return goal[1].trim()
  }
  const quoted = args.match(/^"([^"]+)"/)
  if (quoted?.[1]?.trim()) {
    return quoted[1].trim()
  }
  const stripped = args
    .replace(/--[a-z-]+\s+"[^"]+"/gi, "")
    .replace(/--[a-z-]+\s+[^\s]+/gi, "")
    .trim()
  return stripped || "continue current objective until done"
}

// Parses done-criteria values from command argument string.
export function parseDoneCriteria(args: string): string[] {
  const marker = /--done-criteria\b/i
  const match = args.match(marker)
  if (!match || typeof match.index !== "number") {
    return []
  }
  const start = match.index + match[0].length
  const tail = args.slice(start).trim()
  if (!tail) {
    return []
  }

  let raw = ""
  if (tail.startsWith('"')) {
    const end = tail.indexOf('"', 1)
    raw = end > 1 ? tail.slice(1, end) : ""
  } else if (tail.startsWith("'")) {
    const end = tail.indexOf("'", 1)
    raw = end > 1 ? tail.slice(1, end) : ""
  } else {
    const nextFlag = tail.search(/\s+--[a-z-]+\b/i)
    raw = (nextFlag >= 0 ? tail.slice(0, nextFlag) : tail).trim()
  }

  if (!raw) {
    return []
  }
  return raw
    .split(/[;\n]+/)
    .map((item) => item.trim())
    .filter(Boolean)
}

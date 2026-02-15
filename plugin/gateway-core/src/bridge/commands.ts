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

// Resolves action semantics for autopilot command names and argument forms.
export function resolveAutopilotAction(name: string, args: string): "start" | "stop" | "none" {
  if (isAutopilotStopCommand(name)) {
    return "stop"
  }
  if (!isAutopilotCommand(name)) {
    return "none"
  }
  if (name === "autopilot") {
    const head = args.trim().split(/\s+/)[0]?.toLowerCase() ?? ""
    if (head === "stop" || head === "pause") {
      return "stop"
    }
  }
  return "start"
}

// Returns true when command should start or continue autopilot loop.
export function isAutopilotCommand(name: string): boolean {
  return (
    name === "autopilot" ||
    name === "autopilot-go" ||
    name === "ralph-loop" ||
    name === "continue-work" ||
    name === "autopilot-objective"
  )
}

// Returns true when command should stop active autopilot loop.
export function isAutopilotStopCommand(name: string): boolean {
  return name === "autopilot-stop" || name === "cancel-ralph"
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
  if (!Number.isFinite(parsed) || parsed < 1) {
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

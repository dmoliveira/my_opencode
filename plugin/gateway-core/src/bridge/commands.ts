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

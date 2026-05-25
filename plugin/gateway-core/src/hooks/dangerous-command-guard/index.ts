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

function remediationHint(command: string): string {
  const normalized = command.trim().toLowerCase()
  if (/\brm\s+-rf\b/.test(normalized)) {
    return "Safer alternatives: inspect with `ls` or `git status`, or remove a narrower known path manually outside gateway automation if deletion is truly intended."
  }
  if (/\bgit\s+reset\s+--hard\b/.test(normalized)) {
    return "Safer alternatives: inspect with `git diff --stat`, stash with `git stash push`, or restore a specific file with `git restore --source <ref> -- <path>`."
  }
  if (/\bgit\s+checkout\s+--\b/.test(normalized)) {
    return "Safer alternative: use `git restore --source <ref> -- <path>` for explicit file restore after reviewing the target path."
  }
  if (/\bgit\s+clean\s+-fdx\b/.test(normalized)) {
    return "Safer alternatives: preview with `git clean -ndx`, or remove only a specific generated directory after inspection."
  }
  if (/\bgit\s+push\s+--force\b/.test(normalized)) {
    return "Safer alternatives: use a normal `git push`, or coordinate a force-push manually outside gateway automation only when branch history rewrite is explicitly intended."
  }
  if (/curl\s+[^|]+\|\s*bash/.test(normalized)) {
    return "Safer alternatives: download the script first, inspect it, then run the reviewed file explicitly if still needed."
  }
  return "Safer alternative: inspect the target first and rerun a narrower non-destructive command."
}

// Creates dangerous command guard hook for destructive shell command prevention.
export function createDangerousCommandGuardHook(options: {
  directory: string
  enabled: boolean
  blockedPatterns: string[]
}): GatewayHook {
  const compiled = options.blockedPatterns
    .map((pattern) => {
      try {
        return new RegExp(pattern, "i")
      } catch {
        return null
      }
    })
    .filter((value): value is RegExp => value !== null)
  return {
    id: "dangerous-command-guard",
    priority: 390,
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
      if (tool !== "bash") {
        return
      }
      const command = String(eventPayload.output?.args?.command ?? "").trim()
      if (!command) {
        return
      }
      const matched = compiled.find((regex) => regex.test(command))
      if (!matched) {
        return
      }
      const sessionId = String(eventPayload.input?.sessionID ?? eventPayload.input?.sessionId ?? "")
      writeGatewayEventAudit(directory, {
        hook: "dangerous-command-guard",
        stage: "skip",
        reason_code: "dangerous_command_blocked",
        session_id: sessionId,
        blocked_command: command,
      })
      const hint = remediationHint(command)
      throw new Error(
        `Blocked dangerous bash command: ${command}. ${hint}`,
      )
    },
  }
}

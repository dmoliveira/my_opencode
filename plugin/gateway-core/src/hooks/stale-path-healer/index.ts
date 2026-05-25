import { execFileSync } from "node:child_process"
import { existsSync } from "node:fs"
import { dirname, isAbsolute, join, resolve, sep } from "node:path"

import { writeGatewayEventAudit } from "../../audit/event-audit.js"
import type { GatewayHook } from "../registry.js"

interface ToolArgs {
  workdir?: string
  cwd?: string
  filePath?: string
  path?: string
  file_path?: string
  patchText?: string
  patch_text?: string
}

interface ToolBeforePayload {
  input?: { tool?: string; sessionID?: string; sessionId?: string }
  output?: { args?: ToolArgs }
  directory?: string
}

function gitTopLevel(directory: string): string {
  try {
    return execFileSync("git", ["rev-parse", "--show-toplevel"], {
      cwd: directory,
      encoding: "utf-8",
      stdio: ["ignore", "pipe", "ignore"],
    }).trim()
  } catch {
    return ""
  }
}

function nearestExistingParent(path: string): string {
  let current = path
  while (current && !existsSync(current)) {
    const parent = dirname(current)
    if (parent === current) {
      break
    }
    current = parent
  }
  return current
}

function normalizeDirectory(directory: string, fallback: string): string {
  const trimmed = directory.trim()
  if (!trimmed) {
    return fallback
  }
  if (existsSync(trimmed)) {
    return trimmed
  }
  const existingParent = nearestExistingParent(trimmed)
  return gitTopLevel(existingParent) || existingParent || fallback
}

function maybeRewriteStaleWorktreePath(targetPath: string, activeRoot: string): string {
  if (!targetPath || !isAbsolute(targetPath) || existsSync(targetPath)) {
    return targetPath
  }
  const rootName = activeRoot.split(sep).filter(Boolean).pop() ?? ""
  if (!rootName) {
    return targetPath
  }
  const parts = targetPath.split(sep).filter(Boolean)
  const rootIndex = parts.findIndex(
    (part) => part === rootName || part.startsWith(`${rootName}-wt-`),
  )
  if (rootIndex < 0) {
    return targetPath
  }
  const suffix = parts.slice(rootIndex + 1)
  const candidate = suffix.length > 0 ? join(activeRoot, ...suffix) : activeRoot
  const existingParent = nearestExistingParent(candidate)
  if (!existingParent) {
    return targetPath
  }
  const normalizedParent = existingParent.endsWith(sep) ? existingParent : `${existingParent}${sep}`
  const normalizedRoot = activeRoot.endsWith(sep) ? activeRoot : `${activeRoot}${sep}`
  if (candidate === activeRoot || normalizedParent.startsWith(normalizedRoot)) {
    return candidate
  }
  return targetPath
}

function rewritePatchText(patchText: string, activeRoot: string): string {
  if (!patchText.trim()) {
    return patchText
  }
  return patchText.replace(
    /^(\*\*\*\s+(?:Add|Update|Delete)\s+File:\s+|\*\*\*\s+Move to:\s+)(.+)$/gm,
    (_match, prefix: string, pathValue: string) => `${prefix}${maybeRewriteStaleWorktreePath(pathValue.trim(), activeRoot)}`,
  )
}

export function createStalePathHealerHook(options: { directory: string; enabled: boolean }): GatewayHook {
  const activeRoot = normalizeDirectory(gitTopLevel(options.directory) || options.directory, options.directory)
  return {
    id: "stale-path-healer",
    priority: 305,
    async event(type: string, payload: unknown): Promise<void> {
      if (!options.enabled || type !== "tool.execute.before") {
        return
      }
      const eventPayload = (payload ?? {}) as ToolBeforePayload
      const args = eventPayload.output?.args
      if (!args) {
        return
      }
      const sessionId = String(eventPayload.input?.sessionID ?? eventPayload.input?.sessionId ?? "")
      const auditChanges: Record<string, string> = {}
      const baseDirectory = normalizeDirectory(
        typeof eventPayload.directory === "string" ? eventPayload.directory : "",
        activeRoot,
      )

      const explicitWorkdir = String(args.workdir ?? args.cwd ?? "").trim()
      if (explicitWorkdir) {
        const resolvedWorkdir = isAbsolute(explicitWorkdir)
          ? explicitWorkdir
          : resolve(baseDirectory, explicitWorkdir)
        if (!existsSync(resolvedWorkdir)) {
          const healedWorkdir = maybeRewriteStaleWorktreePath(resolvedWorkdir, activeRoot)
          const rewritten = existsSync(healedWorkdir) ? healedWorkdir : activeRoot
          if (args.workdir !== undefined) {
            args.workdir = rewritten
            auditChanges.workdir = rewritten
          }
          if (args.cwd !== undefined) {
            args.cwd = rewritten
            auditChanges.cwd = rewritten
          }
        }
      }

      for (const key of ["filePath", "path", "file_path"] as const) {
        const raw = String(args[key] ?? "").trim()
        if (!raw || !isAbsolute(raw) || existsSync(raw)) {
          continue
        }
        const rewritten = maybeRewriteStaleWorktreePath(raw, activeRoot)
        if (rewritten !== raw) {
          args[key] = rewritten
          auditChanges[key] = rewritten
        }
      }

      const patchText = String(args.patchText ?? args.patch_text ?? "")
      if (patchText.trim()) {
        const rewrittenPatch = rewritePatchText(patchText, activeRoot)
        if (rewrittenPatch !== patchText) {
          if (args.patchText !== undefined) {
            args.patchText = rewrittenPatch
          }
          if (args.patch_text !== undefined) {
            args.patch_text = rewrittenPatch
          }
          auditChanges.patch_text = "rewritten"
        }
      }

      if (Object.keys(auditChanges).length > 0) {
        writeGatewayEventAudit(activeRoot, {
          hook: "stale-path-healer",
          stage: "state",
          reason_code: "stale_path_rewritten",
          session_id: sessionId,
          tool: String(eventPayload.input?.tool ?? ""),
          changes: auditChanges,
        })
      }
    },
  }
}

import { createHmac, randomBytes, timingSafeEqual } from "node:crypto"
import type { TaskerReadAuthority } from "./read-policy.js"
const immutableResearchArgs = new WeakSet<object>()
export function markTaskerResearchArgs(args: object): void {
  immutableResearchArgs.add(args)
}
export function isTaskerResearchArgs(args: unknown): boolean {
  return Boolean(
    args && typeof args === "object" && immutableResearchArgs.has(args),
  )
}

export const TASKER_RESEARCH_AGENTS = new Set(["explore", "librarian"])
export const TASKER_RESEARCH_CONSTRAINTS = [
  "read-only",
  "no writes",
  "no Codememory",
  "no delegation",
  "no tests or builds",
  "no git or gh",
] as const
export type TaskerResearchPacket = {
  objective: string
  paths: string[]
  acceptance: string
  checks: string
  evidence: string
  constraints: string[]
}

/** Free text never grants tools; descendants are separately restricted by ancestry. */
export function inspectResearchPacket(
  prompt: unknown,
): TaskerResearchPacket | null {
  if (
    typeof prompt !== "string" ||
    prompt.length > 12000 ||
    prompt.includes("[DELEGATION TRACE ")
  )
    return null
  let raw: unknown
  try {
    raw = JSON.parse(prompt)
  } catch {
    return null
  }
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null
  const p = raw as Record<string, unknown>
  if (
    Object.keys(p).sort().join(",") !==
    "acceptance,checks,constraints,evidence,objective,paths"
  )
    return null
  for (const key of ["objective", "acceptance", "checks", "evidence"]) {
    if (
      typeof p[key] !== "string" ||
      !p[key].trim() ||
      p[key].length > 2000 ||
      /[\0\r]/.test(p[key])
    )
      return null
  }
  if (
    !Array.isArray(p.paths) ||
    p.paths.length < 1 ||
    p.paths.length > 8 ||
    !p.paths.every((path) => {
      if (
        typeof path !== "string" ||
        !path ||
        path.length > 1024 ||
        /[\0\r\n]/.test(path)
      )
        return false
      if (path.startsWith("https://")) {
        try {
          const url = new URL(path)
          return !url.username && !url.password
        } catch {
          return false
        }
      }
      return (
        !/[?*\[\]{}]/.test(path) && !path.startsWith("/") && !path.startsWith("\\") &&
        !path.startsWith("~") &&
        !path.split(/[\\/]/).includes("..") &&
        !path.includes(":")
      )
    })
  )
    return null
  if (
    !Array.isArray(p.constraints) ||
    p.constraints.length !== TASKER_RESEARCH_CONSTRAINTS.length ||
    !TASKER_RESEARCH_CONSTRAINTS.every((v) =>
      (p.constraints as unknown[]).includes(v),
    )
  )
    return null
  // Deliberately conservative: research objectives must not request implementation.
  if (
    /\b(?:implement|apply_patch|commit|push|merge|delete|mutate|run\s+(?:tests?|builds?)|oc\s+(?:add|set|link))\b/i.test(
      [p.objective, p.acceptance, p.checks, p.evidence].join(" "),
    )
  )
    return null
  return p as TaskerResearchPacket
}
export function researchBoundary(packet: TaskerResearchPacket): string {
  return `\n\n[Tasker research boundary]\nRead-only research within: ${packet.paths.join(", ")}. ${TASKER_RESEARCH_CONSTRAINTS.join("; ")}. Return concise evidence; do not execute implementation or validation.`
}

export type ResearchAuthority = TaskerReadAuthority & { parent: string; target: string; nonce: string; version: 1 }
/** A child can reconstruct only the capability its native parent actually issued. */
export function createResearchAuthoritySigner(): {
  issue(capability: ResearchAuthority): string
  verify(prompt: string, parent: string): ResearchAuthority | null
} {
  const key = randomBytes(32)
  return {
    issue(capability): string {
      const data = Buffer.from(JSON.stringify(capability)).toString("base64url")
      const mac = createHmac("sha256", key).update(data).digest("base64url")
      return `\n[Tasker read authority ${data}.${mac}]`
    },
    verify(prompt, parent): ResearchAuthority | null {
      const matches = [...prompt.matchAll(/\[Tasker read authority ([A-Za-z0-9_-]{1,24000})\.([A-Za-z0-9_-]{43})\]/g)]
      if (matches.length !== 1) return null
      const [, data, mac] = matches[0]
      const expected = createHmac("sha256", key).update(data).digest()
      const actual = Buffer.from(mac, "base64url")
      if (actual.length !== expected.length || !timingSafeEqual(actual, expected)) return null
      try {
        const cap = JSON.parse(Buffer.from(data, "base64url").toString("utf8")) as ResearchAuthority
        if (cap.version !== 1 || cap.parent !== parent || !TASKER_RESEARCH_AGENTS.has(cap.target) || typeof cap.worktree !== "string" || typeof cap.nonce !== "string" || !Array.isArray(cap.paths) || cap.paths.length < 1 || cap.paths.length > 8 || !cap.paths.every((p) => typeof p === "string")) return null
        return cap
      } catch { return null }
    },
  }
}

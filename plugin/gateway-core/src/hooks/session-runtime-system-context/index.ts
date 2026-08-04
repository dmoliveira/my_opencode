import { existsSync, readFileSync, readdirSync, statSync } from "node:fs"
import { homedir } from "node:os"
import { join, resolve } from "node:path"

import { writeGatewayEventAudit } from "../../audit/event-audit.js"
import { REASON_CODES } from "../../bridge/reason-codes.js"
import { exactPromptFingerprint } from "../../cache/prompt-cache.js"
import { loadGatewayState } from "../../state/storage.js"
import type { GatewayHook } from "../registry.js"
import {
  managedRuntimeSystemMarker,
  RUNTIME_CONCISE_CONTEXT_MARKER,
  RUNTIME_SESSION_CONTEXT_MARKER,
} from "../shared/stable-system-context.js"

interface SystemTransformPayload {
  input?: {
    sessionID?: string
    sessionId?: string
  }
  output?: {
    system?: string[]
  }
  directory?: string
}

const SYSTEM_CONTEXT_MARKER = RUNTIME_SESSION_CONTEXT_MARKER
const CONCISE_CONTEXT_MARKER = RUNTIME_CONCISE_CONTEXT_MARKER
const VALID_MODES = new Set(["off", "lite", "full", "ultra", "review", "commit"])
const COMPACT_CONCISE_RUNTIME_CONTRACT = [
  "Cut filler, pleasantries, and weak hedging; preserve technical substance.",
  "Keep code blocks, technical terms, paths, identifiers, commands, flags, and exact errors unchanged.",
  "lite: concise sentences. full: terse fragments when clear. ultra: strongest safe compression.",
  "Expand for destructive warnings, security/privacy, blockers, ordered steps, repeated confusion, or requests for detail.",
  "Pattern: [problem]. [cause]. [fix]. [next step].",
].join("\n")

// Derived from agents_md/skills/concise-mode/SKILL.md after frontmatter removal
// and trim. New canonical revisions must register a reviewed additive mapping.
const CANONICAL_CONCISE_RUNTIME_CONTRACTS = new Map<
  string,
  { compactKind: "canonical-v1"; body: string }
>([
  [
    "bf27645f37241c9c852c030192f582a341d04376286a90e9c34bf5635d596580",
    {
      compactKind: "canonical-v1",
      body: COMPACT_CONCISE_RUNTIME_CONTRACT,
    },
  ],
])

interface ConciseSkillCandidateCacheEntry {
  siblingSignature: string
  candidates: string[]
}

interface ConciseSkillBodyCacheEntry {
  signature: string
  body: string
}

type ConciseSkillSourceKind = "file" | "fallback"
type ConciseSkillCompactKind = "canonical-v1" | "fallback" | "passthrough"

interface LoadedConciseSkillBody {
  body: string
  sourceKind: ConciseSkillSourceKind
}

interface RuntimeConciseSkillBody extends LoadedConciseSkillBody {
  compactKind: ConciseSkillCompactKind
}

function resolveSessionId(payload: SystemTransformPayload): string {
  const candidates = [payload.input?.sessionID, payload.input?.sessionId]
  for (const value of candidates) {
    if (typeof value === "string" && value.trim()) {
      return value.trim()
    }
  }
  return ""
}

function pathSignature(path: string): string {
  if (!existsSync(path)) {
    return "missing"
  }
  try {
    const stats = statSync(path)
    return [stats.dev, stats.ino, stats.mode, stats.size, stats.mtimeMs, stats.ctimeMs].join(":")
  } catch {
    return "missing"
  }
}

export function stablePromptFingerprint(entries: string[]): string {
  return exactPromptFingerprint(entries)
}

function buildSystemContext(sessionId: string): string {
  return [
    `${SYSTEM_CONTEXT_MARKER} ${sessionId}`,
    "Use this exact runtime session ID for session-scoped commits/logs/telemetry/external tooling; if asked for the current runtime session ID, return only it.",
  ].join("\n")
}

function reconcileRuntimeContexts(
  system: string[],
  conciseContext: string | null,
  sessionContext: string | null,
): { changed: boolean; conciseChanged: boolean; sessionChanged: boolean } {
  const managed = system.filter((entry) => managedRuntimeSystemMarker(entry) !== null)
  const currentConcise = managed.filter(
    (entry) => managedRuntimeSystemMarker(entry) === CONCISE_CONTEXT_MARKER,
  )
  const currentSession = managed.filter(
    (entry) => managedRuntimeSystemMarker(entry) === SYSTEM_CONTEXT_MARKER,
  )
  const desired = [conciseContext, sessionContext].filter(
    (entry): entry is string => typeof entry === "string",
  )
  const conciseChanged =
    currentConcise.length !== (conciseContext ? 1 : 0) ||
    (conciseContext !== null && currentConcise[0] !== conciseContext)
  const sessionChanged =
    currentSession.length !== (sessionContext ? 1 : 0) ||
    (sessionContext !== null && currentSession[0] !== sessionContext)
  const managedTail = desired.length === 0 ? [] : system.slice(-desired.length)
  const changed =
    conciseChanged ||
    sessionChanged ||
    managed.length !== desired.length ||
    managedTail.some((entry, index) => entry !== desired[index])
  if (!changed) {
    return { changed: false, conciseChanged: false, sessionChanged: false }
  }
  const unmanaged = system.filter((entry) => managedRuntimeSystemMarker(entry) === null)
  system.splice(0, system.length, ...unmanaged, ...desired)
  return {
    changed: true,
    conciseChanged: conciseChanged || conciseContext !== null,
    sessionChanged: sessionChanged || sessionContext !== null,
  }
}

function resolveConfiguredConciseMode(options: {
  directory: string
  sessionId: string
  conciseModeEnabled: boolean
  conciseDefaultMode: "off" | "lite" | "full" | "ultra"
}): { mode: string; source: string } | null {
  const state = loadGatewayState(options.directory)
  const stateMode = String(state?.conciseMode?.mode ?? "").trim().toLowerCase()
  const stateSessionId = String(state?.conciseMode?.sessionId ?? "").trim()
  if (
    VALID_MODES.has(stateMode) &&
    stateSessionId === options.sessionId
  ) {
    return { mode: stateMode, source: String(state?.conciseMode?.source ?? "state") }
  }
  if (options.conciseModeEnabled && options.conciseDefaultMode !== "off") {
    return { mode: options.conciseDefaultMode, source: "config_default" }
  }
  return null
}

function candidateSkillPaths(
  directory: string,
  candidateCacheByDirectory: Map<string, ConciseSkillCandidateCacheEntry>,
): string[] {
  const home = String(process.env.HOME ?? "").trim() || homedir()
  const siblingsRoot = resolve(directory, "..")
  const siblingSignature = pathSignature(siblingsRoot)
  const cached = candidateCacheByDirectory.get(directory)
  if (cached?.siblingSignature === siblingSignature) {
    return cached.candidates
  }
  const candidates = [
    resolve(directory, "skills", "concise-mode", "SKILL.md"),
    resolve(directory, "..", "agents_md", "skills", "concise-mode", "SKILL.md"),
    resolve(directory, "..", "agents.md", "skills", "concise-mode", "SKILL.md"),
    join(home, ".config", "opencode", "agents_md", "skills", "concise-mode", "SKILL.md"),
  ]
  try {
    const siblings = readdirSync(siblingsRoot, { withFileTypes: true })
    for (const entry of siblings) {
      if (!entry.isDirectory() || !entry.name.startsWith("agents_md")) {
        continue
      }
      candidates.push(resolve(directory, "..", entry.name, "skills", "concise-mode", "SKILL.md"))
    }
  } catch {
    // best-effort sibling worktree discovery only
  }
  candidateCacheByDirectory.set(directory, {
    siblingSignature,
    candidates,
  })
  return candidates
}

function loadConciseSkillBody(
  directory: string,
  candidateCacheByDirectory: Map<string, ConciseSkillCandidateCacheEntry>,
  bodyCacheByPath: Map<string, ConciseSkillBodyCacheEntry>,
): LoadedConciseSkillBody {
  for (const path of candidateSkillPaths(directory, candidateCacheByDirectory)) {
    if (!existsSync(path)) {
      continue
    }
    const signature = pathSignature(path)
    const cached = bodyCacheByPath.get(path)
    if (cached?.signature === signature) {
      return { body: cached.body, sourceKind: "file" }
    }
    try {
      const text = readFileSync(path, "utf-8")
      const body = text.replace(/^---[\s\S]*?---\s*/, "").trim()
      bodyCacheByPath.set(path, { signature, body })
      return { body, sourceKind: "file" }
    } catch {
      continue
    }
  }
  return { body: COMPACT_CONCISE_RUNTIME_CONTRACT, sourceKind: "fallback" }
}

function resolveRuntimeConciseSkillBody(
  loaded: LoadedConciseSkillBody,
): RuntimeConciseSkillBody {
  if (loaded.sourceKind === "fallback") {
    return {
      ...loaded,
      body: COMPACT_CONCISE_RUNTIME_CONTRACT,
      compactKind: "fallback",
    }
  }
  const registered = CANONICAL_CONCISE_RUNTIME_CONTRACTS.get(
    exactPromptFingerprint([loaded.body]),
  )
  if (registered) {
    return {
      ...loaded,
      body: registered.body,
      compactKind: registered.compactKind,
    }
  }
  return { ...loaded, compactKind: "passthrough" }
}

function modeSpecificRules(mode: string): string {
  if (mode === "review") {
    return "Use one-line review findings when possible. Put blockers first. Keep remediation direct."
  }
  if (mode === "commit") {
    return "Draft terse commit messages. Keep why over what. Prefer one compact sentence when it stays accurate."
  }
  if (mode === "lite") {
    return "Active level: lite. Keep full sentences, but cut filler and pleasantries."
  }
  if (mode === "ultra") {
    return "Active level: ultra. Maximize safe compression. Expand if terseness would hide risk or meaning."
  }
  return "Active level: full. Prefer short direct fragments when they stay clear and technically exact."
}

function buildConciseModeContext(
  directory: string,
  mode: string,
  candidateCacheByDirectory: Map<string, ConciseSkillCandidateCacheEntry>,
  bodyCacheByPath: Map<string, ConciseSkillBodyCacheEntry>,
): string {
  const loaded = resolveRuntimeConciseSkillBody(
    loadConciseSkillBody(directory, candidateCacheByDirectory, bodyCacheByPath),
  )
  const includeModeRule =
    loaded.compactKind === "passthrough" || mode === "review" || mode === "commit"
  return [
    `${CONCISE_CONTEXT_MARKER} ${mode}`,
    includeModeRule ? modeSpecificRules(mode) : "",
    loaded.body,
  ]
    .filter((entry) => entry.length > 0)
    .join("\n")
}

export function createSessionRuntimeSystemContextHook(options: {
  directory: string
  enabled: boolean
  injectSessionIdContext?: boolean
  injectSessionIdWhenConciseModeOnly?: boolean
  conciseModeEnabled: boolean
  conciseDefaultMode: "off" | "lite" | "full" | "ultra"
}): GatewayHook {
  const conciseSkillCandidateCacheByDirectory = new Map<string, ConciseSkillCandidateCacheEntry>()
  const conciseSkillBodyCacheByPath = new Map<string, ConciseSkillBodyCacheEntry>()
  return {
    id: "session-runtime-system-context",
    priority: 294,
    async event(type: string, payload: unknown): Promise<void> {
      if (!options.enabled || type !== "experimental.chat.system.transform") {
        return
      }
      const eventPayload = (payload ?? {}) as SystemTransformPayload
      const directory =
        typeof eventPayload.directory === "string" && eventPayload.directory.trim()
          ? eventPayload.directory
          : options.directory
      const sessionId = resolveSessionId(eventPayload)
      const system = eventPayload.output?.system
      if (!sessionId || !Array.isArray(system)) {
        return
      }

      const concise = resolveConfiguredConciseMode({
        directory,
        sessionId,
        conciseModeEnabled: options.conciseModeEnabled,
        conciseDefaultMode: options.conciseDefaultMode,
      })
      const injectSessionIdContext = options.injectSessionIdContext !== false
      const shouldInjectSessionId = injectSessionIdContext &&
        (!options.injectSessionIdWhenConciseModeOnly || (concise && concise.mode !== "off"))
      const nextConcise =
        concise && concise.mode !== "off"
          ? buildConciseModeContext(
              directory,
              concise.mode,
              conciseSkillCandidateCacheByDirectory,
              conciseSkillBodyCacheByPath,
            )
          : null
      const nextSession = shouldInjectSessionId ? buildSystemContext(sessionId) : null
      const reconciliation = reconcileRuntimeContexts(system, nextConcise, nextSession)

      if (!nextConcise) {
        const reasonCode = shouldInjectSessionId
          ? reconciliation.changed
            ? REASON_CODES.SESSION_RUNTIME_WITHOUT_CONCISE_INJECTED
            : null
          : injectSessionIdContext && options.injectSessionIdWhenConciseModeOnly
            ? reconciliation.changed
              ? REASON_CODES.SESSION_RUNTIME_SKIPPED_CONCISE_SCOPE
              : null
            : reconciliation.changed
              ? REASON_CODES.SESSION_RUNTIME_WITHOUT_CONCISE_REMOVED
              : null
        if (reasonCode) {
          writeGatewayEventAudit(directory, {
            hook: "session-runtime-system-context",
            stage: "inject",
            reason_code: reasonCode,
            session_id: sessionId,
          })
        }
        return
      }

      const reasonCode = shouldInjectSessionId
        ? reconciliation.changed
          ? REASON_CODES.SESSION_RUNTIME_WITH_CONCISE_INJECTED
          : null
        : injectSessionIdContext && options.injectSessionIdWhenConciseModeOnly
          ? null
          : reconciliation.changed
            ? REASON_CODES.SESSION_RUNTIME_WITH_CONCISE_SKIPPED
            : null
      if (!reasonCode) {
        return
      }
      writeGatewayEventAudit(directory, {
        hook: "session-runtime-system-context",
        stage: "inject",
        reason_code: reasonCode,
        session_id: sessionId,
        concise_mode: concise?.mode,
        concise_mode_source: concise?.source,
      })
    },
  }
}

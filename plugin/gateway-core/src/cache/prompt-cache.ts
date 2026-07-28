import { createHash } from "node:crypto"
import { existsSync, readFileSync, realpathSync, statSync } from "node:fs"
import { dirname, isAbsolute, join, resolve } from "node:path"

import {
  managedRuntimeSystemMarker,
  RUNTIME_SESSION_CONTEXT_MARKER,
} from "../hooks/shared/stable-system-context.js"

const CACHE_KEY_VERSION = "ocpc-v1"
const MAX_CACHE_KEY_CHARS = 48

function sha256(value: string): Buffer {
  return createHash("sha256").update(value, "utf8").digest()
}

function canonicalPath(path: string): string {
  try {
    return realpathSync.native(path)
  } catch {
    return resolve(path)
  }
}

function gitCommonDirectory(gitEntry: string, worktreeRoot: string): string | null {
  let gitDirectory = gitEntry
  try {
    const stats = statSync(gitEntry)
    if (stats.isFile()) {
      const match = /^gitdir:\s*(.+)$/m.exec(readFileSync(gitEntry, "utf8"))
      if (!match?.[1]?.trim()) {
        return null
      }
      const candidate = match[1].trim()
      gitDirectory = isAbsolute(candidate)
        ? candidate
        : resolve(worktreeRoot, candidate)
    } else if (!stats.isDirectory()) {
      return null
    }
  } catch {
    return null
  }

  const commonPath = join(gitDirectory, "commondir")
  if (existsSync(commonPath)) {
    try {
      const candidate = readFileSync(commonPath, "utf8").trim()
      if (candidate) {
        return canonicalPath(isAbsolute(candidate) ? candidate : resolve(gitDirectory, candidate))
      }
    } catch {
      return canonicalPath(gitDirectory)
    }
  }
  return canonicalPath(gitDirectory)
}

export function resolvePromptCacheScopeIdentity(directory: string): string {
  const fallback = canonicalPath(directory)
  let current = fallback
  while (true) {
    const gitEntry = join(current, ".git")
    if (existsSync(gitEntry)) {
      return gitCommonDirectory(gitEntry, current) ?? fallback
    }
    const parent = dirname(current)
    if (parent === current) {
      return fallback
    }
    current = parent
  }
}

export interface StablePromptCacheKeyInput {
  scopeIdentity: string
  providerID: string
  modelID: string
  agent: string
  sessionID: string
  shardCount: number
}

export interface StablePromptCacheKeyResult {
  key: string
  shard: number
  shardCount: number
}

export function stablePromptCacheKey(
  input: StablePromptCacheKeyInput,
): StablePromptCacheKeyResult | null {
  const scopeIdentity = input.scopeIdentity.trim()
  const providerID = input.providerID.trim().toLowerCase()
  const modelID = input.modelID.trim().toLowerCase()
  const agent = input.agent.trim().toLowerCase()
  const sessionID = input.sessionID.trim()
  const shardCount = input.shardCount
  if (
    !scopeIdentity ||
    !providerID ||
    !modelID ||
    !agent ||
    !sessionID ||
    !Number.isInteger(shardCount) ||
    shardCount < 1 ||
    shardCount > 64
  ) {
    return null
  }

  const scopeFrame = JSON.stringify([
    CACHE_KEY_VERSION,
    scopeIdentity,
    providerID,
    modelID,
    agent,
  ])
  const scopeDigest = sha256(scopeFrame).toString("hex").slice(0, 24)
  const sessionDigest = sha256(`${CACHE_KEY_VERSION}\u0000${sessionID}`)
  const shard = sessionDigest.readUInt32BE(0) % shardCount
  const key = `${CACHE_KEY_VERSION}:${scopeDigest}:n${shardCount}:s${shard}`
  if (key.length > MAX_CACHE_KEY_CHARS || !/^[a-z0-9:-]+$/.test(key)) {
    return null
  }
  return { key, shard, shardCount }
}

export interface CacheableSystemPrefixObservation {
  sha256: string
  entryCount: number
  charCount: number
  sessionMarkerPresent: boolean
}

export function exactPromptFingerprint(entries: string[]): string {
  return sha256(JSON.stringify(entries)).toString("hex")
}

export function cacheableSystemPrefixObservation(
  system: string[],
): CacheableSystemPrefixObservation {
  const sessionIndex = system.findIndex(
    (entry) => managedRuntimeSystemMarker(entry) === RUNTIME_SESSION_CONTEXT_MARKER,
  )
  const prefix = sessionIndex < 0 ? system : system.slice(0, sessionIndex)
  return {
    sha256: exactPromptFingerprint(prefix),
    entryCount: prefix.length,
    charCount: prefix.reduce((total, entry) => total + entry.length, 0),
    sessionMarkerPresent: sessionIndex >= 0,
  }
}

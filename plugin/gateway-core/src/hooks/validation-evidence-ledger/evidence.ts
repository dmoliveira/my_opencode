import { randomBytes } from "node:crypto"
import {
  chmodSync,
  closeSync,
  constants,
  existsSync,
  fsyncSync,
  lstatSync,
  mkdirSync,
  openSync,
  readFileSync,
  renameSync,
  unlinkSync,
  writeFileSync,
} from "node:fs"
import { dirname, resolve } from "node:path"

import {
  captureGitStateFingerprint,
  type GitStateFingerprint,
  sameGitState,
} from "./git-state.js"

export type ValidationEvidenceCategory = "lint" | "test" | "typecheck" | "build" | "security"

export type ValidationEvidenceSource = "session" | "worktree" | "session+worktree" | "none"

export interface ValidationEvidenceSnapshot {
  lint: boolean
  test: boolean
  typecheck: boolean
  build: boolean
  security: boolean
  updatedAt: string
}

interface ValidationEvidenceRecord {
  fingerprint: GitStateFingerprint
  evidence: ValidationEvidenceSnapshot
}

interface PersistedValidationEvidence {
  version: 2
  worktrees: Record<string, ValidationEvidenceRecord>
}

const MAX_EVIDENCE_BYTES = 1024 * 1024
const evidenceBySession = new Map<string, ValidationEvidenceRecord>()

function emptyEvidence(): ValidationEvidenceSnapshot {
  return {
    lint: false,
    test: false,
    typecheck: false,
    build: false,
    security: false,
    updatedAt: "",
  }
}

function emptyPersistedEvidence(): PersistedValidationEvidence {
  return { version: 2, worktrees: {} }
}

function evidenceFilePath(fingerprint: GitStateFingerprint): string {
  return resolve(fingerprint.root, ".opencode", "runtime", "validation-evidence.json")
}

function assertSafeDirectory(path: string, options: { privateDirectory: boolean }): void {
  const state = lstatSync(path)
  if (!state.isDirectory() || state.isSymbolicLink()) {
    throw new Error(`unsafe validation evidence directory: ${path}`)
  }
  if (state.mode & 0o022) {
    throw new Error(`writable validation evidence directory: ${path}`)
  }
  if (options.privateDirectory && state.mode & 0o077) {
    chmodSync(path, 0o700)
  }
}

function ensureEvidenceDirectory(filePath: string): void {
  const runtimeDirectory = dirname(filePath)
  const opencodeDirectory = dirname(runtimeDirectory)
  if (!existsSync(opencodeDirectory)) {
    mkdirSync(opencodeDirectory, { mode: 0o700 })
  }
  assertSafeDirectory(opencodeDirectory, { privateDirectory: false })
  if (!existsSync(runtimeDirectory)) {
    mkdirSync(runtimeDirectory, { mode: 0o700 })
  }
  assertSafeDirectory(runtimeDirectory, { privateDirectory: true })
}

function safeEvidenceFileState(
  path: string,
  options: { requirePrivate: boolean },
): ReturnType<typeof lstatSync> | null {
  let state: ReturnType<typeof lstatSync>
  try {
    state = lstatSync(path)
  } catch (error) {
    const code = (error as { code?: string }).code
    if (code === "ENOENT") {
      return null
    }
    throw error
  }
  if (!state.isFile() || state.isSymbolicLink() || state.nlink !== 1) {
    throw new Error("unsafe validation evidence file")
  }
  if (options.requirePrivate && state.mode & 0o077) {
    throw new Error("validation evidence file is not owner-only")
  }
  if (state.size > MAX_EVIDENCE_BYTES) {
    throw new Error("validation evidence file exceeds size limit")
  }
  return state
}

function isFingerprint(value: unknown): value is GitStateFingerprint {
  if (!value || typeof value !== "object") {
    return false
  }
  const item = value as Record<string, unknown>
  return (
    item.version === "git-state-v1" &&
    typeof item.root === "string" &&
    item.root.length > 0 &&
    typeof item.head === "string" &&
    /^[a-f0-9]{40,64}$/.test(item.head) &&
    typeof item.index === "string" &&
    /^[a-f0-9]{64}$/.test(item.index) &&
    typeof item.worktree === "string" &&
    /^[a-f0-9]{64}$/.test(item.worktree) &&
    typeof item.digest === "string" &&
    /^[a-f0-9]{64}$/.test(item.digest)
  )
}

function isEvidenceSnapshot(value: unknown): value is ValidationEvidenceSnapshot {
  if (!value || typeof value !== "object") {
    return false
  }
  const item = value as Record<string, unknown>
  return (
    typeof item.lint === "boolean" &&
    typeof item.test === "boolean" &&
    typeof item.typecheck === "boolean" &&
    typeof item.build === "boolean" &&
    typeof item.security === "boolean" &&
    typeof item.updatedAt === "string"
  )
}

function isEvidenceRecord(value: unknown): value is ValidationEvidenceRecord {
  if (!value || typeof value !== "object") {
    return false
  }
  const item = value as Record<string, unknown>
  return isFingerprint(item.fingerprint) && isEvidenceSnapshot(item.evidence)
}

function readPersistedEvidence(fingerprint: GitStateFingerprint): PersistedValidationEvidence {
  const filePath = evidenceFilePath(fingerprint)
  try {
    const runtimeDirectory = dirname(filePath)
    const opencodeDirectory = dirname(runtimeDirectory)
    if (!existsSync(opencodeDirectory) || !existsSync(runtimeDirectory)) {
      return emptyPersistedEvidence()
    }
    assertSafeDirectory(opencodeDirectory, { privateDirectory: false })
    assertSafeDirectory(runtimeDirectory, { privateDirectory: false })
    if (lstatSync(runtimeDirectory).mode & 0o077) {
      return emptyPersistedEvidence()
    }
    const state = safeEvidenceFileState(filePath, { requirePrivate: true })
    if (!state) {
      return emptyPersistedEvidence()
    }
    const payload = JSON.parse(readFileSync(filePath, "utf-8")) as unknown
    if (!payload || typeof payload !== "object") {
      return emptyPersistedEvidence()
    }
    const source = payload as Record<string, unknown>
    if (source.version !== 2 || !source.worktrees || typeof source.worktrees !== "object") {
      return emptyPersistedEvidence()
    }
    const worktrees: Record<string, ValidationEvidenceRecord> = {}
    for (const [key, value] of Object.entries(source.worktrees as Record<string, unknown>)) {
      if (key && isEvidenceRecord(value)) {
        worktrees[key] = value
      }
    }
    return { version: 2, worktrees }
  } catch {
    return emptyPersistedEvidence()
  }
}

function syncDirectory(path: string): void {
  let descriptor: number | null = null
  try {
    descriptor = openSync(path, constants.O_RDONLY)
    fsyncSync(descriptor)
  } catch {
    // The file fsync and atomic rename remain authoritative when directory fsync is unsupported.
  } finally {
    if (descriptor !== null) {
      closeSync(descriptor)
    }
  }
}

function writePersistedEvidence(
  fingerprint: GitStateFingerprint,
  persisted: PersistedValidationEvidence,
): void {
  const filePath = evidenceFilePath(fingerprint)
  ensureEvidenceDirectory(filePath)
  safeEvidenceFileState(filePath, { requirePrivate: false })
  const directory = dirname(filePath)
  const temporaryPath = `${filePath}.${process.pid}.${randomBytes(8).toString("hex")}.tmp`
  const flags = constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | (constants.O_NOFOLLOW ?? 0)
  let descriptor: number | null = null
  try {
    descriptor = openSync(temporaryPath, flags, 0o600)
    writeFileSync(descriptor, `${JSON.stringify(persisted, null, 2)}\n`, "utf-8")
    fsyncSync(descriptor)
    closeSync(descriptor)
    descriptor = null
    chmodSync(temporaryPath, 0o600)
    renameSync(temporaryPath, filePath)
    syncDirectory(directory)
  } finally {
    if (descriptor !== null) {
      closeSync(descriptor)
    }
    if (existsSync(temporaryPath)) {
      unlinkSync(temporaryPath)
    }
  }
}

function evidenceForFingerprint(
  record: ValidationEvidenceRecord | undefined,
  fingerprint: GitStateFingerprint,
): ValidationEvidenceSnapshot {
  return record && sameGitState(record.fingerprint, fingerprint)
    ? { ...record.evidence }
    : emptyEvidence()
}

function mergeEvidence(
  sessionSnapshot: ValidationEvidenceSnapshot,
  worktreeSnapshot: ValidationEvidenceSnapshot,
): ValidationEvidenceSnapshot {
  return {
    lint: sessionSnapshot.lint || worktreeSnapshot.lint,
    test: sessionSnapshot.test || worktreeSnapshot.test,
    typecheck: sessionSnapshot.typecheck || worktreeSnapshot.typecheck,
    build: sessionSnapshot.build || worktreeSnapshot.build,
    security: sessionSnapshot.security || worktreeSnapshot.security,
    updatedAt: sessionSnapshot.updatedAt || worktreeSnapshot.updatedAt,
  }
}

function computeMissing(snapshot: ValidationEvidenceSnapshot, markers: string[]): string[] {
  const missing: string[] = []
  for (const marker of markers) {
    const normalized = marker.trim().toLowerCase()
    if (!normalized) {
      continue
    }
    if (normalized === "validation") {
      if (!(snapshot.lint || snapshot.test || snapshot.typecheck || snapshot.build || snapshot.security)) {
        missing.push(normalized)
      }
      continue
    }
    const category = markerCategory(normalized)
    if (!category || !snapshot[category]) {
      missing.push(normalized)
    }
  }
  return missing
}

export function markerCategory(marker: string): ValidationEvidenceCategory | null {
  const value = marker.trim().toLowerCase()
  if (!value) {
    return null
  }
  if (value.includes("lint")) {
    return "lint"
  }
  if (value.includes("test")) {
    return "test"
  }
  if (value.includes("type") || value.includes("tsc") || value.includes("mypy") || value.includes("pyright")) {
    return "typecheck"
  }
  if (value.includes("build") || value.includes("compile")) {
    return "build"
  }
  if (
    value.includes("security") ||
    value.includes("audit") ||
    value.includes("semgrep") ||
    value.includes("codeql")
  ) {
    return "security"
  }
  return null
}

export function validationEvidence(sessionId: string, directory = ""): ValidationEvidenceSnapshot {
  const key = sessionId.trim()
  const record = key ? evidenceBySession.get(key) : undefined
  if (!record) {
    return emptyEvidence()
  }
  if (!directory.trim()) {
    return { ...record.evidence }
  }
  const fingerprint = captureGitStateFingerprint(directory)
  return fingerprint ? evidenceForFingerprint(record, fingerprint) : emptyEvidence()
}

export function worktreeValidationEvidence(directory: string): ValidationEvidenceSnapshot {
  const fingerprint = captureGitStateFingerprint(directory)
  if (!fingerprint) {
    return emptyEvidence()
  }
  const record = readPersistedEvidence(fingerprint).worktrees[fingerprint.root]
  return evidenceForFingerprint(record, fingerprint)
}

export function markValidationEvidence(
  sessionId: string,
  categories: ValidationEvidenceCategory[],
  directory = "",
  expectedFingerprint?: GitStateFingerprint,
): ValidationEvidenceSnapshot {
  const key = sessionId.trim()
  const fingerprint = captureGitStateFingerprint(directory)
  if (!key || categories.length === 0 || !fingerprint || (expectedFingerprint && !sameGitState(expectedFingerprint, fingerprint))) {
    return emptyEvidence()
  }

  const next = evidenceForFingerprint(evidenceBySession.get(key), fingerprint)
  for (const category of categories) {
    next[category] = true
  }
  next.updatedAt = new Date().toISOString()

  const persisted = readPersistedEvidence(fingerprint)
  const scoped = evidenceForFingerprint(persisted.worktrees[fingerprint.root], fingerprint)
  for (const category of categories) {
    scoped[category] = true
  }
  scoped.updatedAt = next.updatedAt
  persisted.worktrees[fingerprint.root] = { fingerprint, evidence: scoped }
  writePersistedEvidence(fingerprint, persisted)
  evidenceBySession.set(key, { fingerprint, evidence: next })
  return { ...next }
}

export function clearValidationEvidence(sessionId: string): void {
  const key = sessionId.trim()
  if (key) {
    evidenceBySession.delete(key)
  }
}

export function missingValidationMarkers(sessionId: string, markers: string[], directory = ""): string[] {
  return computeMissing(validationEvidence(sessionId, directory), markers)
}

export function validationEvidenceStatus(
  sessionId: string,
  markers: string[],
  directory = "",
): { missing: string[]; source: ValidationEvidenceSource } {
  const fingerprint = captureGitStateFingerprint(directory)
  if (!fingerprint) {
    return { missing: [...markers], source: "none" }
  }
  const sessionSnapshot = evidenceForFingerprint(
    evidenceBySession.get(sessionId.trim()),
    fingerprint,
  )
  const sessionMissing = computeMissing(sessionSnapshot, markers)
  if (sessionMissing.length === 0) {
    return { missing: [], source: "session" }
  }
  const worktreeSnapshot = evidenceForFingerprint(
    readPersistedEvidence(fingerprint).worktrees[fingerprint.root],
    fingerprint,
  )
  const worktreeMissing = computeMissing(worktreeSnapshot, markers)
  if (worktreeMissing.length === 0) {
    return { missing: [], source: "worktree" }
  }
  const merged = mergeEvidence(sessionSnapshot, worktreeSnapshot)
  const mergedMissing = computeMissing(merged, markers)
  return mergedMissing.length === 0
    ? { missing: [], source: "session+worktree" }
    : { missing: mergedMissing, source: "none" }
}

export { captureGitStateFingerprint, type GitStateFingerprint, sameGitState }

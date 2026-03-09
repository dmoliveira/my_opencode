import { execFileSync } from "node:child_process"

// Declares evidence categories tracked by validation ledger.
export type ValidationEvidenceCategory = "lint" | "test" | "typecheck" | "build" | "security"

export type ValidationEvidenceSource = "session" | "worktree" | "session+worktree" | "none"

// Declares normalized evidence snapshot for one session.
export interface ValidationEvidenceSnapshot {
  lint: boolean
  test: boolean
  typecheck: boolean
  build: boolean
  security: boolean
  updatedAt: string
}

const evidenceBySession = new Map<string, ValidationEvidenceSnapshot>()
const evidenceByWorktree = new Map<string, ValidationEvidenceSnapshot>()

// Returns blank evidence snapshot.
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

function evidenceScopeKey(directory: string): string {
  const cwd = directory.trim()
  if (!cwd) {
    return ""
  }
  try {
    const root = execFileSync("git", ["rev-parse", "--show-toplevel"], {
      cwd,
      stdio: ["ignore", "pipe", "ignore"],
    })
      .toString("utf-8")
      .trim()
    const branch = execFileSync("git", ["rev-parse", "--abbrev-ref", "HEAD"], {
      cwd,
      stdio: ["ignore", "pipe", "ignore"],
    })
      .toString("utf-8")
      .trim()
    return `${root}::${branch || cwd}`
  } catch {
    return cwd
  }
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
    const category = markerCategory(normalized)
    if (!category) {
      continue
    }
    if (!snapshot[category]) {
      missing.push(normalized)
    }
  }
  return missing
}

// Resolves evidence category for marker token when supported.
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

// Returns immutable snapshot for session evidence.
export function validationEvidence(sessionId: string): ValidationEvidenceSnapshot {
  if (!sessionId.trim()) {
    return emptyEvidence()
  }
  const current = evidenceBySession.get(sessionId.trim())
  if (!current) {
    return emptyEvidence()
  }
  return { ...current }
}

// Returns immutable snapshot for worktree/branch-scoped evidence.
export function worktreeValidationEvidence(directory: string): ValidationEvidenceSnapshot {
  const key = evidenceScopeKey(directory)
  if (!key) {
    return emptyEvidence()
  }
  const current = evidenceByWorktree.get(key)
  if (!current) {
    return emptyEvidence()
  }
  return { ...current }
}

// Marks one or more evidence categories as validated.
export function markValidationEvidence(
  sessionId: string,
  categories: ValidationEvidenceCategory[],
  directory = "",
): ValidationEvidenceSnapshot {
  const key = sessionId.trim()
  if (!key) {
    return emptyEvidence()
  }
  const next = {
    ...validationEvidence(key),
  }
  for (const category of categories) {
    next[category] = true
  }
  next.updatedAt = new Date().toISOString()
  evidenceBySession.set(key, next)
  const scopeKey = evidenceScopeKey(directory)
  if (scopeKey) {
    const scoped = {
      ...worktreeValidationEvidence(directory),
    }
    for (const category of categories) {
      scoped[category] = true
    }
    scoped.updatedAt = next.updatedAt
    evidenceByWorktree.set(scopeKey, scoped)
  }
  return { ...next }
}

// Clears evidence state for one session.
export function clearValidationEvidence(sessionId: string): void {
  const key = sessionId.trim()
  if (!key) {
    return
  }
  evidenceBySession.delete(key)
}

// Returns missing marker list based on current ledger evidence.
export function missingValidationMarkers(sessionId: string, markers: string[]): string[] {
  return computeMissing(validationEvidence(sessionId), markers)
}

// Returns validation status across session and optional worktree fallback.
export function validationEvidenceStatus(
  sessionId: string,
  markers: string[],
  directory = "",
): { missing: string[]; source: ValidationEvidenceSource } {
  const sessionSnapshot = validationEvidence(sessionId)
  const sessionMissing = computeMissing(sessionSnapshot, markers)
  if (sessionMissing.length === 0) {
    return { missing: [], source: "session" }
  }
  const worktreeSnapshot = worktreeValidationEvidence(directory)
  const worktreeMissing = computeMissing(worktreeSnapshot, markers)
  if (worktreeMissing.length === 0 && directory.trim()) {
    return { missing: [], source: "worktree" }
  }
  const merged = mergeEvidence(sessionSnapshot, worktreeSnapshot)
  const mergedMissing = computeMissing(merged, markers)
  if (mergedMissing.length === 0 && directory.trim()) {
    return { missing: [], source: "session+worktree" }
  }
  return { missing: mergedMissing, source: "none" }
}

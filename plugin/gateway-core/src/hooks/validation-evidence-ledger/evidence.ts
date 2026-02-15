// Declares evidence categories tracked by validation ledger.
export type ValidationEvidenceCategory = "lint" | "test" | "typecheck" | "build" | "security"

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

// Marks one or more evidence categories as validated.
export function markValidationEvidence(
  sessionId: string,
  categories: ValidationEvidenceCategory[],
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
  const snapshot = validationEvidence(sessionId)
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

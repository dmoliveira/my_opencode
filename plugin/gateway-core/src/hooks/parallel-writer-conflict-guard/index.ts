import { readFileSync } from "node:fs"
import { resolve } from "node:path"

import { writeGatewayEventAudit } from "../../audit/event-audit.js"
import type { GatewayHook } from "../registry.js"

interface ToolBeforePayload {
  input?: {
    tool?: string
    sessionID?: string
    sessionId?: string
  }
  output?: {
    args?: {
      filePath?: string
      path?: string
      file_path?: string
      patchText?: string
      patch_text?: string
    }
  }
  directory?: string
}

// Normalizes file path for stable matching.
function normalizePath(value: string): string {
  return value.replace(/\\/g, "/").replace(/^\.\//, "").trim()
}

// Escapes regex metacharacters in literal text.
function escapeRegex(value: string): string {
  return value.replace(/[|\\{}()[\]^$+?.*]/g, "\\$&")
}

// Converts simple glob pattern to regex.
function globToRegex(pattern: string): RegExp {
  const normalized = normalizePath(pattern)
  const escaped = escapeRegex(normalized)
    .replace(/\\\*\\\*/g, ":::DOUBLE_STAR:::")
    .replace(/\\\*/g, "[^/]*")
    .replace(/:::DOUBLE_STAR:::/g, ".*")
  return new RegExp(`^${escaped}$`)
}

// Splits env path list by comma/semicolon/newline separators.
function envPathList(keys: string[]): string[] {
  return keys
    .flatMap((key) => String(process.env[key] ?? "").split(/[\n,;]+/))
    .map((item) => normalizePath(item))
    .filter(Boolean)
}

// Resolves max active writer count from configured env markers.
function activeWriterCount(keys: string[]): number {
  let max = 0
  for (const key of keys) {
    const value = Number.parseInt(String(process.env[key] ?? ""), 10)
    if (Number.isFinite(value) && value > max) {
      max = value
    }
  }
  return max
}

interface ReservationState {
  writerCount?: number
  writer_count?: number
  ownPaths?: string[]
  own_paths?: string[]
  activePaths?: string[]
  active_paths?: string[]
}

function readReservationState(directory: string, stateFile: string): ReservationState {
  try {
    const content = readFileSync(resolve(directory, stateFile), "utf-8")
    const parsed = JSON.parse(content)
    return parsed && typeof parsed === "object" ? (parsed as ReservationState) : {}
  } catch {
    return {}
  }
}

function statePathList(state: ReservationState, keys: Array<keyof ReservationState>): string[] {
  const values = keys.flatMap((key) => {
    const value = state[key]
    return Array.isArray(value) ? value : []
  })
  return values.map((item) => normalizePath(String(item))).filter(Boolean)
}

// Resolves target paths touched by write-like operation.
function touchedPaths(tool: string, payload: ToolBeforePayload): string[] {
  const args = payload.output?.args
  if (tool === "write" || tool === "edit") {
    const direct = String(args?.filePath ?? args?.path ?? args?.file_path ?? "").trim()
    return direct ? [normalizePath(direct)] : []
  }
  if (tool !== "apply_patch") {
    return []
  }
  const patch = String(args?.patchText ?? args?.patch_text ?? "")
  if (!patch.trim()) {
    return []
  }
  const paths = patch
    .split(/\r?\n/)
    .filter((line) => /^\*\*\* (Add|Update|Delete) File: /i.test(line) || /^\*\*\* Move to: /i.test(line))
    .map((line) =>
      line
        .replace(/^\*\*\* (Add|Update|Delete) File: /i, "")
        .replace(/^\*\*\* Move to: /i, "")
        .trim(),
    )
    .map((line) => normalizePath(line))
    .filter(Boolean)
  return Array.from(new Set(paths))
}

// Returns true when path matches at least one pattern.
function matchesAny(path: string, patterns: string[]): boolean {
  return patterns.some((pattern) => {
    try {
      return globToRegex(pattern).test(path)
    } catch {
      return false
    }
  })
}

// Creates parallel writer conflict guard for reservation and concurrency policy.
export function createParallelWriterConflictGuardHook(options: {
  directory: string
  enabled: boolean
  maxConcurrentWriters: number
  writerCountEnvKeys: string[]
  reservationPathsEnvKeys: string[]
  activeReservationPathsEnvKeys: string[]
  enforceReservationCoverage: boolean
  stateFile: string
}): GatewayHook {
  const maxConcurrentWriters =
    Number.isFinite(options.maxConcurrentWriters) && options.maxConcurrentWriters > 0
      ? options.maxConcurrentWriters
      : 2
  return {
    id: "parallel-writer-conflict-guard",
    priority: 436,
    async event(type: string, payload: unknown): Promise<void> {
      if (!options.enabled || type !== "tool.execute.before") {
        return
      }
      const eventPayload = (payload ?? {}) as ToolBeforePayload
      const tool = String(eventPayload.input?.tool ?? "").toLowerCase()
      if (tool !== "write" && tool !== "edit" && tool !== "apply_patch") {
        return
      }
      const directory =
        typeof eventPayload.directory === "string" && eventPayload.directory.trim()
          ? eventPayload.directory
          : options.directory
      const sessionId = String(eventPayload.input?.sessionID ?? eventPayload.input?.sessionId ?? "")
      const reservationState = readReservationState(directory, options.stateFile)

      const stateWriterCount = Number(
        reservationState.writerCount ?? reservationState.writer_count ?? 0,
      )
      const writerCount = Math.max(
        activeWriterCount(options.writerCountEnvKeys),
        Number.isFinite(stateWriterCount) ? stateWriterCount : 0,
      )
      if (writerCount > maxConcurrentWriters) {
        writeGatewayEventAudit(directory, {
          hook: "parallel-writer-conflict-guard",
          stage: "skip",
          reason_code: "parallel_writer_limit_exceeded",
          session_id: sessionId,
          active_writers: writerCount,
          max_writers: maxConcurrentWriters,
        })
        throw new Error(
          `[parallel-writer-conflict-guard] Active writer count (${writerCount}) exceeds limit (${maxConcurrentWriters}).`,
        )
      }

      const paths = touchedPaths(tool, eventPayload)
      if (paths.length === 0) {
        return
      }
      const ownReservations = Array.from(
        new Set([
          ...envPathList(options.reservationPathsEnvKeys),
          ...statePathList(reservationState, ["ownPaths", "own_paths"]),
        ]),
      )
      const activeReservations = Array.from(
        new Set([
          ...envPathList(options.activeReservationPathsEnvKeys),
          ...statePathList(reservationState, ["activePaths", "active_paths"]),
        ]),
      )

      if (options.enforceReservationCoverage && ownReservations.length > 0) {
        const uncovered = paths.filter((path) => !matchesAny(path, ownReservations))
        if (uncovered.length > 0) {
          writeGatewayEventAudit(directory, {
            hook: "parallel-writer-conflict-guard",
            stage: "skip",
            reason_code: "parallel_writer_reservation_uncovered",
            session_id: sessionId,
            uncovered_path_count: uncovered.length,
          })
          throw new Error(
            `[parallel-writer-conflict-guard] Edit path is outside reserved ownership: ${uncovered.join(", ")}.`,
          )
        }
      }

      if (activeReservations.length > 0) {
        const conflicts = paths.filter(
          (path) => matchesAny(path, activeReservations) && !matchesAny(path, ownReservations),
        )
        if (conflicts.length > 0) {
          writeGatewayEventAudit(directory, {
            hook: "parallel-writer-conflict-guard",
            stage: "skip",
            reason_code: "parallel_writer_overlap_detected",
            session_id: sessionId,
            conflict_path_count: conflicts.length,
          })
          throw new Error(
            `[parallel-writer-conflict-guard] Path overlaps an active reservation: ${conflicts.join(", ")}.`,
          )
        }
      }
    },
  }
}

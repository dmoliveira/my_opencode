import { constants as fsConstants } from "node:fs"
import { lstat, open } from "node:fs/promises"
import { join } from "node:path"

export const EXECUTION_STATUS_FILE = "gateway-core.state.json"
export const EXECUTION_STATUS_DIRECTORY = ".opencode"
// Matches the gateway state protocol while remaining bounded on every refresh.
export const MAX_STATE_BYTES = 4 * 1024 * 1024
export const MAX_LABEL_CHARS = 160
export const MAX_STATUS_AGE_MS = 24 * 60 * 60 * 1000

const CONTROL_CHARACTER = /[\u0000-\u001f\u007f]/

export type ExecutionStatusEntry = {
  sessionId: string
  last: string
  next: string
  updatedAt: string
}

export type ExecutionStatusSnapshot = {
  version: 1
  sessions: Record<string, ExecutionStatusEntry>
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value))
}

function setOwn<T>(target: Record<string, T>, key: string, value: T): void {
  Object.defineProperty(target, key, {
    value,
    enumerable: true,
    configurable: true,
    writable: true,
  })
}

function isSafeText(value: unknown): value is string {
  return (
    typeof value === "string" &&
    value.trim().length > 0 &&
    value.length <= MAX_LABEL_CHARS &&
    !CONTROL_CHARACTER.test(value)
  )
}

function isSafeSessionId(value: unknown): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= 160 && !CONTROL_CHARACTER.test(value)
}

function isSafeTimestamp(value: unknown): value is string {
  return typeof value === "string" && Number.isFinite(Date.parse(value))
}

function isOwnedByCurrentUser(value: { uid: number }): boolean {
  return typeof process.getuid !== "function" || value.uid === process.getuid()
}

function isPrivateStateDirectory(value: {
  isDirectory(): boolean
  isSymbolicLink(): boolean
  mode: number
  uid: number
}): boolean {
  return (
    value.isDirectory() &&
    !value.isSymbolicLink() &&
    isOwnedByCurrentUser(value) &&
    (value.mode & 0o777) === 0o700
  )
}

function isPrivateStateFile(value: {
  isFile(): boolean
  isSymbolicLink(): boolean
  mode: number
  nlink: number
  uid: number
}): boolean {
  return (
    value.isFile() &&
    !value.isSymbolicLink() &&
    value.nlink === 1 &&
    isOwnedByCurrentUser(value) &&
    (value.mode & 0o777) === 0o600
  )
}

function sameFile(left: { dev: number; ino: number }, right: { dev: number; ino: number }): boolean {
  return left.dev === right.dev && left.ino === right.ino
}

export function parseExecutionStatus(value: unknown): ExecutionStatusSnapshot | null {
  if (!isRecord(value) || value.version !== 1 || !isRecord(value.sessions)) {
    return null
  }
  const sessions = Object.create(null) as Record<string, ExecutionStatusEntry>
  for (const [sessionId, entry] of Object.entries(value.sessions)) {
    if (
      !isSafeSessionId(sessionId) ||
      !isRecord(entry) ||
      entry.sessionId !== sessionId ||
      !isSafeText(entry.last) ||
      !isSafeText(entry.next) ||
      !isSafeTimestamp(entry.updatedAt)
    ) {
      continue
    }
    setOwn(sessions, sessionId, {
      sessionId,
      last: entry.last,
      next: entry.next,
      updatedAt: entry.updatedAt,
    })
  }
  return { version: 1, sessions }
}

export function executionStatusPath(directory: string): string {
  return join(directory, EXECUTION_STATUS_DIRECTORY, EXECUTION_STATUS_FILE)
}

// Reads only a private, bounded gateway state file and fails closed on unsafe input.
export async function readExecutionStatus(directory: string): Promise<ExecutionStatusSnapshot | null> {
  const stateDirectory = join(directory, EXECUTION_STATUS_DIRECTORY)
  const path = join(stateDirectory, EXECUTION_STATUS_FILE)
  let handle: Awaited<ReturnType<typeof open>> | undefined
  try {
    if (typeof fsConstants.O_NOFOLLOW !== "number") {
      return null
    }
    const directoryBefore = await lstat(stateDirectory)
    if (!isPrivateStateDirectory(directoryBefore)) {
      return null
    }
    const link = await lstat(path)
    if (!isPrivateStateFile(link) || link.size <= 0 || link.size > MAX_STATE_BYTES) {
      return null
    }
    handle = await open(path, fsConstants.O_RDONLY | fsConstants.O_NOFOLLOW)
    const stats = await handle.stat()
    const directoryAfter = await lstat(stateDirectory)
    if (
      !isPrivateStateDirectory(directoryAfter) ||
      !sameFile(directoryBefore, directoryAfter) ||
      !isPrivateStateFile(stats) ||
      !sameFile(link, stats) ||
      stats.size <= 0 ||
      stats.size > MAX_STATE_BYTES
    ) {
      return null
    }
    const content = Buffer.alloc(Number(stats.size))
    const result = await handle.read(content, 0, content.length, 0)
    if (result.bytesRead !== content.length) {
      return null
    }
    const parsed = JSON.parse(content.toString("utf8"))
    return parseExecutionStatus(isRecord(parsed) ? parsed.executionStatus : null)
  } catch {
    return null
  } finally {
    await handle?.close().catch(() => undefined)
  }
}

export function statusForSession(
  snapshot: ExecutionStatusSnapshot | null,
  sessionId: string,
  now = Date.now(),
): ExecutionStatusEntry | null {
  const entry = snapshot?.sessions[sessionId]
  if (!entry) {
    return null
  }
  const updatedAt = Date.parse(entry.updatedAt)
  if (!Number.isFinite(updatedAt) || updatedAt > now + 5 * 60 * 1000 || now - updatedAt > MAX_STATUS_AGE_MS) {
    return null
  }
  return entry
}

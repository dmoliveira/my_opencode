import { closeSync, openSync, readSync } from "node:fs"

const DEFAULT_PREFIX_SLACK_BYTES = 1024

export function readFilePrefix(path: string, maxChars: number): string {
  const safeLimit = Number.isFinite(maxChars) && maxChars > 0 ? Math.floor(maxChars) : 1
  const maxBytes = safeLimit + DEFAULT_PREFIX_SLACK_BYTES
  let fd: number | null = null
  try {
    fd = openSync(path, "r")
    const buffer = Buffer.alloc(maxBytes)
    const bytesRead = readSync(fd, buffer, 0, maxBytes, 0)
    return buffer.subarray(0, bytesRead).toString("utf-8")
  } catch {
    return ""
  } finally {
    if (fd !== null) {
      closeSync(fd)
    }
  }
}

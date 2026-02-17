import { appendFileSync, existsSync, mkdirSync, renameSync, statSync } from "node:fs"
import { dirname, join } from "node:path"

// Returns true when gateway event auditing is enabled.
export function gatewayEventAuditEnabled(): boolean {
  const raw = process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT ?? ""
  const value = raw.trim().toLowerCase()
  return value === "1" || value === "true" || value === "yes" || value === "on"
}

// Resolves gateway event audit file path.
export function gatewayEventAuditPath(directory: string): string {
  const raw = process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT_PATH ?? ""
  if (raw.trim()) {
    return raw.trim()
  }
  return join(directory, ".opencode", "gateway-events.jsonl")
}

function auditMaxBytes(): number {
  const parsed = Number.parseInt(String(process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT_MAX_BYTES ?? ""), 10)
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return 5 * 1024 * 1024
  }
  return parsed
}

function auditMaxBackups(): number {
  const parsed = Number.parseInt(String(process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT_MAX_BACKUPS ?? ""), 10)
  if (!Number.isFinite(parsed) || parsed < 1) {
    return 3
  }
  return parsed
}

function rotateAudit(path: string): void {
  const maxBackups = auditMaxBackups()
  for (let idx = maxBackups; idx >= 1; idx -= 1) {
    const src = `${path}.${idx}`
    const dst = `${path}.${idx + 1}`
    if (existsSync(src)) {
      renameSync(src, dst)
    }
  }
  if (existsSync(path)) {
    renameSync(path, `${path}.1`)
  }
}

// Appends one sanitized gateway event audit entry.
export function writeGatewayEventAudit(
  directory: string,
  entry: Record<string, unknown>,
): void {
  if (!gatewayEventAuditEnabled()) {
    return
  }
  const path = gatewayEventAuditPath(directory)
  mkdirSync(dirname(path), { recursive: true })
  const payload = {
    ts: new Date().toISOString(),
    ...entry,
  }
  const line = `${JSON.stringify(payload)}\n`
  const maxBytes = auditMaxBytes()
  try {
    const currentSize = existsSync(path) ? statSync(path).size : 0
    if (currentSize + Buffer.byteLength(line, "utf-8") > maxBytes) {
      rotateAudit(path)
    }
  } catch {
    // Best-effort rotation; continue append even if metadata checks fail.
  }
  appendFileSync(path, line, "utf-8")
}

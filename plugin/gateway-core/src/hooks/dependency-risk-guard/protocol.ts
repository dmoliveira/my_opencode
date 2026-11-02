import { randomBytes } from "node:crypto"

export const AUTH_REQUEST = "dependency-security authorize-uv-sync-locked"
export const SETUP_REQUEST = "uv sync --locked"
export const PENDING_MS = 180_000
export const PERMIT_MS = 60_000
export const MAX_STATE = 128

export interface Scope {
  session: string
  call: string
  root: string
  fingerprint: string
}
export interface Pending extends Scope {
  nonce: string
  command: string
  until: number
  auditorRoot?: string
  auditorFingerprint?: string
}
export interface AuditFrame {
  v: 1
  nonce: string
  fingerprint: string
  packages: number
  closure: string
  auditor: "pip-audit==2.10.1"
  operation: "uv-sync-locked"
  build: "none"
  auditorRoot: string
  auditorFingerprint: string
}

/** Exactly one canonical frame: duplicate keys, chatter and truncated output fail closed. */
export function parseFrame(output: unknown, pending: Pending): AuditFrame {
  if (typeof output !== "string" || Buffer.byteLength(output) > 2048) throw new Error("frame_invalid")
  const value = JSON.parse(output) as AuditFrame
  if (!value || Object.keys(value).join(",") !== "v,nonce,fingerprint,packages,closure,auditor,operation,build,auditorRoot,auditorFingerprint" ||
      JSON.stringify(value) + "\n" !== output || value.v !== 1 || value.nonce !== pending.nonce ||
      value.fingerprint !== pending.fingerprint || !Number.isSafeInteger(value.packages) ||
      value.packages < 1 || value.packages > 512 || !/^[a-f0-9]{64}$/.test(value.closure) ||
      value.auditor !== "pip-audit==2.10.1" || value.operation !== "uv-sync-locked" || value.build !== "none" ||
      typeof value.auditorRoot !== "string" || !value.auditorRoot.startsWith("/") || value.auditorRoot.length > 1024 ||
      !/^[a-f0-9]{64}$/.test(value.auditorFingerprint)) {
    throw new Error("frame_invalid")
  }
  return value
}

/** Host-only, bounded and restart-ephemeral. All transitions are synchronous. */
export class AuthorizationLedger {
  private pending = new Map<string, Pending>()
  private permits = new Map<string, Pending>()
  private seen = new Map<string, number>()

  constructor(private readonly now: () => number = Date.now) {}

  clear(session?: string): void {
    for (const map of [this.pending, this.permits]) {
      for (const [key, value] of map) if (!session || value.session === session) map.delete(key)
    }
  }

  sweep(): void {
    const now = this.now()
    for (const map of [this.pending, this.permits]) {
      for (const [key, value] of map) if (value.until <= now) map.delete(key)
    }
    for (const [key, until] of this.seen) if (until <= now) this.seen.delete(key)
  }

  begin(scope: Scope, command: (nonce: string) => string): Pending {
    this.sweep()
    // Never let a second in-flight request replace the correlation of the first.
    if ([...this.pending.values()].some((value) => value.session === scope.session) ||
        this.pending.size + this.permits.size >= MAX_STATE || this.seen.size >= MAX_STATE ||
        this.seen.has(`${scope.session}\0${scope.call}`)) {
      this.clear(scope.session)
      throw new Error("authorization_conflict")
    }
    this.clear(scope.session)
    const nonce = randomBytes(32).toString("hex")
    const pending = { ...scope, nonce, command: command(nonce), until: this.now() + PENDING_MS }
    this.seen.set(`${scope.session}\0${scope.call}`, pending.until + PERMIT_MS)
    this.pending.set(scope.session, pending)
    return pending
  }

  finish(scope: Scope, command: unknown, exit: unknown, output: unknown, verifyAuditor: (frame: AuditFrame) => void = () => {}): boolean {
    this.sweep()
    const pending = this.pending.get(scope.session)
    this.clear(scope.session)
    if (!pending) return false
    try {
      if (pending.call !== scope.call || pending.root !== scope.root ||
          pending.fingerprint !== scope.fingerprint || pending.command !== command || exit !== 0) return false
      const frame = parseFrame(output, pending)
      verifyAuditor(frame)
      this.permits.set(scope.session, { ...pending, auditorRoot: frame.auditorRoot, auditorFingerprint: frame.auditorFingerprint, until: this.now() + PERMIT_MS })
      return true
    } catch {
      return false
    }
  }

  consume(scope: Scope): Pending {
    this.sweep()
    const permit = this.permits.get(scope.session)
    this.clear(scope.session)
    if (!permit || permit.root !== scope.root || permit.fingerprint !== scope.fingerprint ||
        permit.call === scope.call || this.seen.has(`${scope.session}\0${scope.call}`)) {
      throw new Error("authorization_required")
    }
    this.seen.set(`${scope.session}\0${scope.call}`, this.now() + PENDING_MS + PERMIT_MS)
    return permit
  }
}

import { appendFileSync, existsSync, mkdirSync, readFileSync, renameSync, statSync, unlinkSync } from "node:fs"
import { dirname, join } from "node:path"
import { randomBytes } from "node:crypto"

interface ObservabilitySettings {
  enabled: boolean
  provider: string
  otlpEndpoint: string
  otlpTracesEndpoint: string
  otlpProtocol: string
  otlpHeadersEnv: string
  langfusePublicKeyEnv: string
  langfuseSecretKeyEnv: string
  serviceName: string
}

interface CacheEntry {
  mtimeMs: number
  settings: ObservabilitySettings
}

interface AuditWriterState {
  directoryReady: boolean
  fileSize: number | null
  dedupeByKey: Map<string, number>
}

interface AuditWriteEntry extends Record<string, unknown> {
  audit_dedupe_key?: unknown
  audit_dedupe_window_ms?: unknown
}

interface AuditEnvCacheEntry {
  auditEnabledRaw: string | undefined
  auditEnabled: boolean
  auditPathRaw: string | undefined
  auditPathOverride: string | null
  maxBytesRaw: string | undefined
  maxBytes: number
  maxBackupsRaw: string | undefined
  maxBackups: number
}

interface OtelEnvCacheEntry {
  provider: string
  otlpEndpoint: string
  otlpTracesEndpointSetting: string
  explicitToggleRaw: string | undefined
  tracesEndpointRaw: string | undefined
  defaultTracesEndpointRaw: string | undefined
  explicitHeadersRaw: string | undefined
  headersEnvKey: string
  headersEnvRaw: string | undefined
  defaultHeadersRaw: string | undefined
  langfusePublicKeyEnv: string
  langfusePublicKeyRaw: string | undefined
  langfuseSecretKeyEnv: string
  langfuseSecretKeyRaw: string | undefined
  timeoutRaw: string | undefined
  explicitToggleParsed: boolean | null
  tracesEndpoint: string
  rawHeaders: string
  timeoutMs: number
}

const observabilityCache = new Map<string, CacheEntry>()
const auditWriterCache = new Map<string, AuditWriterState>()
let auditEnvCache: AuditEnvCacheEntry | null = null
let otelEnvCache: OtelEnvCacheEntry | null = null

function parseBool(value: string | undefined, fallback: boolean): boolean {
  if (!value) {
    return fallback
  }
  const normalized = value.trim().toLowerCase()
  if (["1", "true", "yes", "on"].includes(normalized)) {
    return true
  }
  if (["0", "false", "no", "off"].includes(normalized)) {
    return false
  }
  return fallback
}

function parsePositiveInt(value: string | undefined, fallback: number, minimum: number): number {
  const parsed = Number.parseInt(String(value ?? ""), 10)
  if (!Number.isFinite(parsed) || parsed < minimum) {
    return fallback
  }
  return parsed
}

function resolveAuditEnvState(): AuditEnvCacheEntry {
  const auditEnabledRaw = process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
  const auditPathRaw = process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT_PATH
  const maxBytesRaw = process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT_MAX_BYTES
  const maxBackupsRaw = process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT_MAX_BACKUPS
  const cached = auditEnvCache
  if (
    cached &&
    cached.auditEnabledRaw === auditEnabledRaw &&
    cached.auditPathRaw === auditPathRaw &&
    cached.maxBytesRaw === maxBytesRaw &&
    cached.maxBackupsRaw === maxBackupsRaw
  ) {
    return cached
  }
  const next: AuditEnvCacheEntry = {
    auditEnabledRaw,
    auditEnabled: parseBool(auditEnabledRaw, false),
    auditPathRaw,
    auditPathOverride: auditPathRaw?.trim() ? auditPathRaw.trim() : null,
    maxBytesRaw,
    maxBytes: parsePositiveInt(maxBytesRaw, 5 * 1024 * 1024, 1),
    maxBackupsRaw,
    maxBackups: parsePositiveInt(maxBackupsRaw, 3, 1),
  }
  auditEnvCache = next
  return next
}

function defaultObservabilitySettings(): ObservabilitySettings {
  return {
    enabled: false,
    provider: "langfuse",
    otlpEndpoint: "http://localhost:3005/api/public/otel",
    otlpTracesEndpoint: "http://localhost:3005/api/public/otel/v1/traces",
    otlpProtocol: "http/protobuf",
    otlpHeadersEnv: "OTEL_EXPORTER_OTLP_HEADERS",
    langfusePublicKeyEnv: "LANGFUSE_PUBLIC_KEY",
    langfuseSecretKeyEnv: "LANGFUSE_SECRET_KEY",
    serviceName: "my_opencode",
  }
}

function resolveObservabilityConfigPath(directory: string): string {
  const envPath = process.env.OPENCODE_CONFIG_PATH?.trim()
  if (envPath && existsSync(envPath)) {
    return envPath
  }
  const home = process.env.HOME?.trim() || ""
  const userPath = home ? join(home, ".config", "opencode", "opencode.json") : ""
  if (userPath && existsSync(userPath)) {
    return userPath
  }
  return join(directory, "opencode.json")
}

function loadObservabilitySettings(directory: string): ObservabilitySettings {
  const defaultState = defaultObservabilitySettings()
  const configPath = resolveObservabilityConfigPath(directory)
  try {
    const stat = statSync(configPath)
    const cached = observabilityCache.get(configPath)
    if (cached && cached.mtimeMs === stat.mtimeMs) {
      return cached.settings
    }
    const parsed = JSON.parse(readFileSync(configPath, "utf-8")) as {
      observability?: Record<string, unknown>
    }
    const source = parsed.observability && typeof parsed.observability === "object" ? parsed.observability : {}
    const settings: ObservabilitySettings = {
      enabled:
        typeof source.enabled === "boolean" ? source.enabled : defaultState.enabled,
      provider:
        typeof source.provider === "string" && source.provider.trim()
          ? source.provider.trim().toLowerCase()
          : defaultState.provider,
      otlpEndpoint:
        typeof source.otlp_endpoint === "string" && source.otlp_endpoint.trim()
          ? source.otlp_endpoint.trim()
          : defaultState.otlpEndpoint,
      otlpTracesEndpoint:
        typeof source.otlp_traces_endpoint === "string" && source.otlp_traces_endpoint.trim()
          ? source.otlp_traces_endpoint.trim()
          : defaultState.otlpTracesEndpoint,
      otlpProtocol:
        typeof source.otlp_protocol === "string" && source.otlp_protocol.trim()
          ? source.otlp_protocol.trim()
          : defaultState.otlpProtocol,
      otlpHeadersEnv:
        typeof source.otlp_headers_env === "string" && source.otlp_headers_env.trim()
          ? source.otlp_headers_env.trim()
          : defaultState.otlpHeadersEnv,
      langfusePublicKeyEnv:
        typeof source.langfuse_public_key_env === "string" && source.langfuse_public_key_env.trim()
          ? source.langfuse_public_key_env.trim()
          : defaultState.langfusePublicKeyEnv,
      langfuseSecretKeyEnv:
        typeof source.langfuse_secret_key_env === "string" && source.langfuse_secret_key_env.trim()
          ? source.langfuse_secret_key_env.trim()
          : defaultState.langfuseSecretKeyEnv,
      serviceName:
        typeof source.service_name === "string" && source.service_name.trim()
          ? source.service_name.trim()
          : defaultState.serviceName,
    }
    observabilityCache.set(configPath, { mtimeMs: stat.mtimeMs, settings })
    return settings
  } catch {
    return defaultState
  }
}

function parseHeaders(raw: string): Record<string, string> {
  const headers: Record<string, string> = {}
  for (const part of raw.split(",")) {
    const token = part.trim()
    if (!token) {
      continue
    }
    const idx = token.indexOf("=")
    if (idx <= 0) {
      continue
    }
    const key = token.slice(0, idx).trim()
    const value = token.slice(idx + 1).trim()
    if (!key || !value) {
      continue
    }
    headers[key] = value
  }
  return headers
}

function derivedLangfuseAuth(settings: ObservabilitySettings): string {
  const publicKey = process.env[settings.langfusePublicKeyEnv]?.trim() || ""
  const secretKey = process.env[settings.langfuseSecretKeyEnv]?.trim() || ""
  if (!publicKey || !secretKey) {
    return ""
  }
  const encoded = Buffer.from(`${publicKey}:${secretKey}`, "utf-8").toString("base64")
  return `Authorization=Basic ${encoded}`
}

function resolveOtelEnvState(settings: ObservabilitySettings): OtelEnvCacheEntry {
  const explicitToggleRaw = process.env.MY_OPENCODE_OTEL_EXPORT_ENABLED
  const tracesEndpointRaw = process.env.MY_OPENCODE_OTEL_EXPORT_TRACES_ENDPOINT
  const defaultTracesEndpointRaw = process.env.OTEL_EXPORTER_OTLP_TRACES_ENDPOINT
  const explicitHeadersRaw = process.env.MY_OPENCODE_OTEL_EXPORT_HEADERS
  const headersEnvKey = settings.otlpHeadersEnv || "OTEL_EXPORTER_OTLP_HEADERS"
  const headersEnvRaw = process.env[headersEnvKey]
  const defaultHeadersRaw = process.env.OTEL_EXPORTER_OTLP_HEADERS
  const langfusePublicKeyEnv = settings.langfusePublicKeyEnv
  const langfuseSecretKeyEnv = settings.langfuseSecretKeyEnv
  const langfusePublicKeyRaw = process.env[langfusePublicKeyEnv]
  const langfuseSecretKeyRaw = process.env[langfuseSecretKeyEnv]
  const timeoutRaw = process.env.MY_OPENCODE_OTEL_EXPORT_TIMEOUT_MS
  const cached = otelEnvCache
  if (
    cached &&
    cached.provider === settings.provider &&
    cached.otlpEndpoint === settings.otlpEndpoint &&
    cached.otlpTracesEndpointSetting === settings.otlpTracesEndpoint &&
    cached.explicitToggleRaw === explicitToggleRaw &&
    cached.tracesEndpointRaw === tracesEndpointRaw &&
    cached.defaultTracesEndpointRaw === defaultTracesEndpointRaw &&
    cached.explicitHeadersRaw === explicitHeadersRaw &&
    cached.headersEnvKey === headersEnvKey &&
    cached.headersEnvRaw === headersEnvRaw &&
    cached.defaultHeadersRaw === defaultHeadersRaw &&
    cached.langfusePublicKeyEnv === langfusePublicKeyEnv &&
    cached.langfusePublicKeyRaw === langfusePublicKeyRaw &&
    cached.langfuseSecretKeyEnv === langfuseSecretKeyEnv &&
    cached.langfuseSecretKeyRaw === langfuseSecretKeyRaw &&
    cached.timeoutRaw === timeoutRaw
  ) {
    return cached
  }
  const explicitToggleParsed = explicitToggleRaw ? parseBool(explicitToggleRaw, false) : null
  const rawHeaders =
    explicitHeadersRaw?.trim() ||
    headersEnvRaw?.trim() ||
    defaultHeadersRaw?.trim() ||
    (settings.provider === "langfuse" ? derivedLangfuseAuth(settings) : "")
  const next: OtelEnvCacheEntry = {
    provider: settings.provider,
    otlpEndpoint: settings.otlpEndpoint,
    otlpTracesEndpointSetting: settings.otlpTracesEndpoint,
    explicitToggleRaw,
    tracesEndpointRaw,
    defaultTracesEndpointRaw,
    explicitHeadersRaw,
    headersEnvKey,
    headersEnvRaw,
    defaultHeadersRaw,
    langfusePublicKeyEnv,
    langfusePublicKeyRaw,
    langfuseSecretKeyEnv,
    langfuseSecretKeyRaw,
    timeoutRaw,
    explicitToggleParsed,
    tracesEndpoint:
      tracesEndpointRaw?.trim() ||
      defaultTracesEndpointRaw?.trim() ||
      settings.otlpTracesEndpoint ||
      `${settings.otlpEndpoint.replace(/\/$/, "")}/v1/traces`,
    rawHeaders,
    timeoutMs: parsePositiveInt(timeoutRaw, 1500, 1),
  }
  otelEnvCache = next
  return next
}

function normalizeTraceId(value: unknown): string {
  const raw = String(value ?? "").replace(/[^a-fA-F0-9]/g, "").toLowerCase()
  if (raw.length === 32) {
    return raw
  }
  if (raw.length > 32) {
    return raw.slice(0, 32)
  }
  return randomBytes(16).toString("hex")
}

function spanId(): string {
  return randomBytes(8).toString("hex")
}

function nowNanos(): string {
  return (BigInt(Date.now()) * 1_000_000n).toString()
}

function otelAttributes(entry: Record<string, unknown>): Array<Record<string, unknown>> {
  const attrs: Array<Record<string, unknown>> = []
  for (const [key, value] of Object.entries(entry)) {
    if (value === null || value === undefined) {
      continue
    }
    if (typeof value === "string") {
      attrs.push({ key, value: { stringValue: value } })
      continue
    }
    if (typeof value === "number") {
      attrs.push({ key, value: { doubleValue: value } })
      continue
    }
    if (typeof value === "boolean") {
      attrs.push({ key, value: { boolValue: value } })
      continue
    }
    attrs.push({ key, value: { stringValue: JSON.stringify(value) } })
  }
  return attrs
}

function otelSpanPayload(serviceName: string, entry: Record<string, unknown>): Record<string, unknown> {
  const start = nowNanos()
  const end = nowNanos()
  const traceId = normalizeTraceId(entry.trace_id)
  const name = `${String(entry.hook ?? "gateway")}.${String(entry.reason_code ?? "event")}`
  return {
    resourceSpans: [
      {
        resource: {
          attributes: [
            { key: "service.name", value: { stringValue: serviceName } },
            { key: "service.namespace", value: { stringValue: "my_opencode" } },
          ],
        },
        scopeSpans: [
          {
            scope: {
              name: "my_opencode.gateway-core",
              version: "0.1.1",
            },
            spans: [
              {
                traceId,
                spanId: spanId(),
                name,
                kind: 1,
                startTimeUnixNano: start,
                endTimeUnixNano: end,
                attributes: otelAttributes(entry),
                status: {
                  code: 1,
                },
              },
            ],
          },
        ],
      },
    ],
  }
}

function maybeExportOtel(directory: string, entry: Record<string, unknown>): void {
  const explicitEnvToggle = process.env.MY_OPENCODE_OTEL_EXPORT_ENABLED
  if (explicitEnvToggle && !parseBool(explicitEnvToggle, false)) {
    return
  }
  const settings = loadObservabilitySettings(directory)
  const envState = resolveOtelEnvState(settings)
  const envEnabled = envState.explicitToggleParsed ?? settings.enabled
  if (!envEnabled) {
    return
  }
  if (!["langfuse", "otlp"].includes(settings.provider)) {
    return
  }

  const fetchFn = (globalThis as unknown as { fetch?: (url: string, init?: unknown) => Promise<unknown> }).fetch
  if (!fetchFn) {
    return
  }

  const endpoint = envState.tracesEndpoint
  const rawHeaders = envState.rawHeaders
  if (!rawHeaders && settings.provider === "langfuse") {
    return
  }
  const headers = {
    "content-type": "application/json",
    ...(rawHeaders ? parseHeaders(rawHeaders) : {}),
  }
  const payload = otelSpanPayload(settings.serviceName, entry)

  const timeoutMs = envState.timeoutMs
  const controller = typeof AbortController !== "undefined" ? new AbortController() : undefined
  const timer = controller
    ? setTimeout(() => controller.abort(), timeoutMs)
    : undefined

  void fetchFn(endpoint, {
    method: "POST",
    headers,
    body: JSON.stringify(payload),
    signal: controller?.signal,
  })
    .catch(() => undefined)
    .finally(() => {
      if (timer) {
        clearTimeout(timer)
      }
    })
}

function canExportOtel(directory: string): boolean {
  const explicitEnvToggle = process.env.MY_OPENCODE_OTEL_EXPORT_ENABLED
  if (explicitEnvToggle && !parseBool(explicitEnvToggle, false)) {
    return false
  }
  const settings = loadObservabilitySettings(directory)
  const envState = resolveOtelEnvState(settings)
  const envEnabled = envState.explicitToggleParsed ?? settings.enabled
  if (!envEnabled) {
    return false
  }
  if (!["langfuse", "otlp"].includes(settings.provider)) {
    return false
  }
  const fetchFn = (globalThis as unknown as { fetch?: (url: string, init?: unknown) => Promise<unknown> }).fetch
  if (!fetchFn) {
    return false
  }
  const rawHeaders = envState.rawHeaders
  if (!rawHeaders && settings.provider === "langfuse") {
    return false
  }
  return true
}

// Returns true when gateway event auditing is enabled.
export function gatewayEventAuditEnabled(): boolean {
  return resolveAuditEnvState().auditEnabled
}

// Resolves gateway event audit file path.
export function gatewayEventAuditPath(directory: string): string {
  const state = resolveAuditEnvState()
  if (state.auditPathOverride) {
    return state.auditPathOverride
  }
  return join(directory, ".opencode", "gateway-events.jsonl")
}

function auditMaxBytes(): number {
  return resolveAuditEnvState().maxBytes
}

function auditMaxBackups(): number {
  return resolveAuditEnvState().maxBackups
}

function rotateAudit(path: string): void {
  const maxBackups = auditMaxBackups()
  const oldest = `${path}.${maxBackups}`
  if (existsSync(oldest)) {
    try {
      unlinkSync(oldest)
    } catch {
      // Best-effort cleanup; continue rotation even if the oldest backup cannot be removed.
    }
  }
  for (let idx = maxBackups - 1; idx >= 1; idx -= 1) {
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

function resolveAuditWriterState(path: string): AuditWriterState {
  const cached = auditWriterCache.get(path)
  if (cached) {
    return cached
  }
  let fileSize = 0
  try {
    fileSize = existsSync(path) ? statSync(path).size : 0
  } catch {
    fileSize = 0
  }
  const state: AuditWriterState = {
    directoryReady: false,
    fileSize,
    dedupeByKey: new Map<string, number>(),
  }
  auditWriterCache.set(path, state)
  return state
}

// Appends one sanitized gateway event audit entry.
export function writeGatewayEventAudit(
  directory: string,
  entry: Record<string, unknown>,
): void {
  const rawEntry = entry as AuditWriteEntry
  const auditDedupeKey = typeof rawEntry.audit_dedupe_key === "string" && rawEntry.audit_dedupe_key.trim()
    ? rawEntry.audit_dedupe_key.trim()
    : ""
  const auditDedupeWindowMs = Number(rawEntry.audit_dedupe_window_ms)
  const dedupeWindowMs = Number.isFinite(auditDedupeWindowMs) && auditDedupeWindowMs > 0
    ? auditDedupeWindowMs
    : 0
  const { audit_dedupe_key: _auditDedupeKey, audit_dedupe_window_ms: _auditDedupeWindowMs, ...persistedEntry } = rawEntry
  const payload = {
    ts: new Date().toISOString(),
    ...persistedEntry,
  }

  const fileAuditEnabled = gatewayEventAuditEnabled()
  const otelExportEnabled = canExportOtel(directory)
  const path = gatewayEventAuditPath(directory)
  const writerState = resolveAuditWriterState(path)
  if (auditDedupeKey && dedupeWindowMs > 0 && (fileAuditEnabled || otelExportEnabled)) {
    const now = Date.now()
    const previousTs = writerState.dedupeByKey.get(auditDedupeKey) ?? 0
    if (now - previousTs < dedupeWindowMs) {
      return
    }
    writerState.dedupeByKey.set(auditDedupeKey, now)
  }

  if (fileAuditEnabled) {
    if (!writerState.directoryReady) {
      mkdirSync(dirname(path), { recursive: true })
      writerState.directoryReady = true
    }
    const line = `${JSON.stringify(payload)}\n`
    const lineBytes = Buffer.byteLength(line, "utf-8")
    const maxBytes = auditMaxBytes()
    try {
      const currentSize = writerState.fileSize ?? 0
      if (currentSize + lineBytes > maxBytes) {
        rotateAudit(path)
        writerState.fileSize = 0
      }
    } catch {
      // Best-effort rotation; continue append even if metadata checks fail.
      writerState.fileSize = null
    }
    appendFileSync(path, line, "utf-8")
    writerState.fileSize = (writerState.fileSize ?? 0) + lineBytes
  }

  if (otelExportEnabled) {
    maybeExportOtel(directory, payload)
  }
}

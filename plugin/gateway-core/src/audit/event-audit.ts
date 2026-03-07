import { appendFileSync, existsSync, mkdirSync, readFileSync, renameSync, statSync } from "node:fs"
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

const observabilityCache = new Map<string, CacheEntry>()

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
              version: "0.1.0",
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
  const settings = loadObservabilitySettings(directory)
  const envEnabled = parseBool(process.env.MY_OPENCODE_OTEL_EXPORT_ENABLED, settings.enabled)
  if (!envEnabled) {
    return
  }
  if (!["langfuse", "otlp"].includes(settings.provider)) {
    return
  }

  const endpoint =
    process.env.MY_OPENCODE_OTEL_EXPORT_TRACES_ENDPOINT?.trim() ||
    process.env.OTEL_EXPORTER_OTLP_TRACES_ENDPOINT?.trim() ||
    settings.otlpTracesEndpoint ||
    `${settings.otlpEndpoint.replace(/\/$/, "")}/v1/traces`
  const headersEnv = settings.otlpHeadersEnv || "OTEL_EXPORTER_OTLP_HEADERS"
  const rawHeaders =
    process.env.MY_OPENCODE_OTEL_EXPORT_HEADERS?.trim() ||
    process.env[headersEnv]?.trim() ||
    process.env.OTEL_EXPORTER_OTLP_HEADERS?.trim() ||
    derivedLangfuseAuth(settings)
  if (!rawHeaders) {
    return
  }
  const headers = {
    "content-type": "application/json",
    ...parseHeaders(rawHeaders),
  }
  const payload = otelSpanPayload(settings.serviceName, entry)

  const fetchFn = (globalThis as unknown as { fetch?: (url: string, init?: unknown) => Promise<unknown> }).fetch
  if (!fetchFn) {
    return
  }

  const timeoutMs = Number.parseInt(String(process.env.MY_OPENCODE_OTEL_EXPORT_TIMEOUT_MS ?? "1500"), 10)
  const controller = typeof AbortController !== "undefined" ? new AbortController() : undefined
  const timer = controller
    ? setTimeout(() => controller.abort(), Number.isFinite(timeoutMs) && timeoutMs > 0 ? timeoutMs : 1500)
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
  const payload = {
    ts: new Date().toISOString(),
    ...entry,
  }

  if (gatewayEventAuditEnabled()) {
    const path = gatewayEventAuditPath(directory)
    mkdirSync(dirname(path), { recursive: true })
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

  maybeExportOtel(directory, payload)
}

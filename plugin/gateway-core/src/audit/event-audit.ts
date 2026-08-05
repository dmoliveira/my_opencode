import { createHash, randomBytes } from "node:crypto";
import {
  closeSync,
  constants,
  existsSync,
  fchmodSync,
  fstatSync,
  lstatSync,
  mkdirSync,
  openSync,
  readFileSync,
  renameSync,
  statSync,
  unlinkSync,
  writeSync,
} from "node:fs";
import type { Stats } from "node:fs";
import { basename, dirname, join } from "node:path";

interface ObservabilitySettings {
  enabled: boolean;
  provider: string;
  otlpEndpoint: string;
  otlpTracesEndpoint: string;
  otlpProtocol: string;
  otlpHeadersEnv: string;
  langfusePublicKeyEnv: string;
  langfuseSecretKeyEnv: string;
  serviceName: string;
}

interface CacheEntry {
  mtimeMs: number;
  settings: ObservabilitySettings;
}

interface AuditWriterState {
  dedupeByKey: Map<string, number>;
}

interface OpenAuditFile {
  descriptor: number;
  state: Stats;
}

interface AuditWriteEntry extends Record<string, unknown> {
  audit_dedupe_key?: unknown;
  audit_dedupe_window_ms?: unknown;
}

interface AuditEnvCacheEntry {
  auditEnabledRaw: string | undefined;
  auditEnabled: boolean;
  auditPathRaw: string | undefined;
  auditPathOverride: string | null;
  maxBytesRaw: string | undefined;
  maxBytes: number;
  maxBackupsRaw: string | undefined;
  maxBackups: number;
}

interface OtelEnvCacheEntry {
  provider: string;
  otlpEndpoint: string;
  otlpTracesEndpointSetting: string;
  explicitToggleRaw: string | undefined;
  tracesEndpointRaw: string | undefined;
  defaultTracesEndpointRaw: string | undefined;
  explicitHeadersRaw: string | undefined;
  headersEnvKey: string;
  headersEnvRaw: string | undefined;
  defaultHeadersRaw: string | undefined;
  langfusePublicKeyEnv: string;
  langfusePublicKeyRaw: string | undefined;
  langfuseSecretKeyEnv: string;
  langfuseSecretKeyRaw: string | undefined;
  timeoutRaw: string | undefined;
  explicitToggleParsed: boolean | null;
  tracesEndpoint: string;
  rawHeaders: string;
  timeoutMs: number;
}

interface SanitizerState {
  remainingNodes: number;
  seen: WeakSet<object>;
}

type FetchLike = (
  url: string,
  init?: Record<string, unknown>,
) => Promise<unknown>;

interface OtelSinkContext {
  endpoint: string;
  protocol: "http/json";
  serviceName: string;
  headers: Readonly<Record<string, string>>;
  timeoutMs: number;
  fetchFn: FetchLike;
}

interface OtelExportJob {
  body: string;
  sink: OtelSinkContext;
}

interface LocalAggregateAuditBatch {
  directory: string;
  entries: readonly Readonly<Record<string, unknown>>[];
  nextIndex: number;
  succeeded: boolean;
  complete: (success: boolean) => void;
}

interface MutableOtelExportStats {
  enqueued: number;
  sent: number;
  succeeded: number;
  failed: number;
  timedOut: number;
  httpFailures: number;
  dropped: number;
  oversized: number;
}

export interface GatewayEventAuditExportStats extends MutableOtelExportStats {
  queued: number;
  inFlight: number;
}

const MAX_AUDIT_RECORD_BYTES = 64 * 1024;
const MAX_AUDIT_STRING_CHARS = 2048;
const MAX_AUDIT_COLLECTION_ITEMS = 64;
const MAX_AUDIT_DEPTH = 6;
const MAX_AUDIT_NODES = 512;
const MAX_AUDIT_KEY_CHARS = 128;
const MAX_OTLP_ATTRIBUTE_CHARS = 256;
const MAX_OTLP_BODY_BYTES = 32 * 1024;
const MAX_OTLP_QUEUE = 256;
const MAX_LOCAL_AGGREGATE_AUDIT_QUEUE = 256;
const MIN_OTLP_TIMEOUT_MS = 100;
const MAX_OTLP_TIMEOUT_MS = 2000;
const DEFAULT_OTLP_TIMEOUT_MS = 1500;
const PROCESS_UID =
  typeof process.getuid === "function" ? process.getuid() : null;

const LOCAL_AGGREGATE_AUDIT_KEYS = new Set([
  "hook",
  "stage",
  "reason_code",
  "event_class",
  "window_ms",
  "minimum_samples",
  "sample_count",
  "success_count",
  "failure_count",
  "blocked_count",
  "bucket_upper_bounds_ms",
  "bucket_counts",
  "overflow_count",
  "elapsed_total_ms",
  "event_class_elapsed_total_ms",
  "p50_upper_bound_ms",
  "p50_overflow",
  "p95_upper_bound_ms",
  "p95_overflow",
  "p99_upper_bound_ms",
  "p99_overflow",
  "latency_share_pct",
  "optimization_candidate",
  "candidate_gate_names",
  "window_series_total",
  "window_series_enqueued",
  "window_series_dropped",
  "detached_windows_dropped",
  "audit_batches_rejected",
  "audit_batches_failed",
  "series_samples_dropped",
]);

const SENSITIVE_AUDIT_KEYS = new Set([
  "api_key",
  "apikey",
  "arguments",
  "authorization",
  "body",
  "client_secret",
  "command",
  "cookie",
  "error",
  "error_message",
  "file_path",
  "filepath",
  "header",
  "headers",
  "id_token",
  "message",
  "messages",
  "output",
  "outputs",
  "passphrase",
  "passwd",
  "password",
  "path",
  "private_key",
  "prompt",
  "prompts",
  "proxy_authorization",
  "refresh_token",
  "request_body",
  "response_body",
  "secret",
  "set_cookie",
  "stack",
  "stack_trace",
  "stderr",
  "stdout",
  "title",
  "token",
  "x_api_key",
]);

const OTLP_STRING_ATTRIBUTES = new Set([
  "actual_model",
  "event_type",
  "expected_model",
  "hook",
  "mode",
  "observation_source",
  "operation",
  "provider",
  "reason_code",
  "source",
  "stage",
  "status",
]);

const OTLP_BOOLEAN_ATTRIBUTES = new Set([
  "blocked",
  "child_mode",
  "critical",
  "enabled",
  "has_session_id",
  "used_llm",
]);

const OTLP_NUMBER_ATTRIBUTES = new Set([
  "attempt",
  "duration_ms",
  "elapsed_ms",
  "hook_count",
  "limit",
  "loop_attempt_count",
  "sample_rate",
  "selected_hook_count",
]);

const observabilityCache = new Map<string, CacheEntry>();
const auditWriterCache = new Map<string, AuditWriterState>();
const otelQueue: OtelExportJob[] = [];
const localAggregateAuditQueue: LocalAggregateAuditBatch[] = [];
const otelFlushWaiters = new Set<() => void>();
let auditEnvCache: AuditEnvCacheEntry | null = null;
let otelEnvCache: OtelEnvCacheEntry | null = null;
let otelInFlight = false;
let otelGeneration = 0;
let activeOtelController: AbortController | null = null;
let activeOtelTimeout: ReturnType<typeof setTimeout> | null = null;
let otelStats = emptyOtelStats();
let localAggregateAuditScheduled = false;
let localAggregateAuditGeneration = 0;
let localAggregateAuditQueuedRecords = 0;

function emptyOtelStats(): MutableOtelExportStats {
  return {
    enqueued: 0,
    sent: 0,
    succeeded: 0,
    failed: 0,
    timedOut: 0,
    httpFailures: 0,
    dropped: 0,
    oversized: 0,
  };
}

function parseBool(value: string | undefined, fallback: boolean): boolean {
  if (!value) {
    return fallback;
  }
  const normalized = value.trim().toLowerCase();
  if (["1", "true", "yes", "on"].includes(normalized)) {
    return true;
  }
  if (["0", "false", "no", "off"].includes(normalized)) {
    return false;
  }
  return fallback;
}

function parseBoundedInt(
  value: string | undefined,
  fallback: number,
  minimum: number,
  maximum: number,
): number {
  const parsed = Number.parseInt(String(value ?? ""), 10);
  if (!Number.isFinite(parsed)) {
    return fallback;
  }
  return Math.min(maximum, Math.max(minimum, parsed));
}

function resolveAuditEnvState(): AuditEnvCacheEntry {
  const auditEnabledRaw = process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT;
  const auditPathRaw = process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT_PATH;
  const maxBytesRaw = process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT_MAX_BYTES;
  const maxBackupsRaw = process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT_MAX_BACKUPS;
  const cached = auditEnvCache;
  if (
    cached &&
    cached.auditEnabledRaw === auditEnabledRaw &&
    cached.auditPathRaw === auditPathRaw &&
    cached.maxBytesRaw === maxBytesRaw &&
    cached.maxBackupsRaw === maxBackupsRaw
  ) {
    return cached;
  }
  const next: AuditEnvCacheEntry = {
    auditEnabledRaw,
    auditEnabled: parseBool(auditEnabledRaw, false),
    auditPathRaw,
    auditPathOverride: auditPathRaw?.trim() ? auditPathRaw.trim() : null,
    maxBytesRaw,
    maxBytes: parseBoundedInt(
      maxBytesRaw,
      5 * 1024 * 1024,
      1,
      100 * 1024 * 1024,
    ),
    maxBackupsRaw,
    maxBackups: parseBoundedInt(maxBackupsRaw, 3, 1, 20),
  };
  auditEnvCache = next;
  return next;
}

function defaultObservabilitySettings(): ObservabilitySettings {
  return {
    enabled: false,
    provider: "langfuse",
    otlpEndpoint: "http://localhost:3005/api/public/otel",
    otlpTracesEndpoint: "http://localhost:3005/api/public/otel/v1/traces",
    otlpProtocol: "http/json",
    otlpHeadersEnv: "OTEL_EXPORTER_OTLP_HEADERS",
    langfusePublicKeyEnv: "LANGFUSE_PUBLIC_KEY",
    langfuseSecretKeyEnv: "LANGFUSE_SECRET_KEY",
    serviceName: "my_opencode",
  };
}

function resolveObservabilityConfigPath(directory: string): string {
  const envPath = process.env.OPENCODE_CONFIG_PATH?.trim();
  if (envPath && existsSync(envPath)) {
    return envPath;
  }
  const home = process.env.HOME?.trim() || "";
  const userPath = home
    ? join(home, ".config", "opencode", "opencode.json")
    : "";
  if (userPath && existsSync(userPath)) {
    return userPath;
  }
  return join(directory, "opencode.json");
}

function loadObservabilitySettings(directory: string): ObservabilitySettings {
  const defaultState = defaultObservabilitySettings();
  const configPath = resolveObservabilityConfigPath(directory);
  try {
    const stat = statSync(configPath);
    const cached = observabilityCache.get(configPath);
    if (cached && cached.mtimeMs === stat.mtimeMs) {
      return cached.settings;
    }
    const parsed = JSON.parse(readFileSync(configPath, "utf-8")) as {
      observability?: Record<string, unknown>;
    };
    const source =
      parsed.observability && typeof parsed.observability === "object"
        ? parsed.observability
        : {};
    const settings: ObservabilitySettings = {
      enabled:
        typeof source.enabled === "boolean"
          ? source.enabled
          : defaultState.enabled,
      provider:
        typeof source.provider === "string" && source.provider.trim()
          ? source.provider.trim().toLowerCase()
          : defaultState.provider,
      otlpEndpoint:
        typeof source.otlp_endpoint === "string" && source.otlp_endpoint.trim()
          ? source.otlp_endpoint.trim()
          : defaultState.otlpEndpoint,
      otlpTracesEndpoint:
        typeof source.otlp_traces_endpoint === "string" &&
        source.otlp_traces_endpoint.trim()
          ? source.otlp_traces_endpoint.trim()
          : defaultState.otlpTracesEndpoint,
      otlpProtocol:
        typeof source.otlp_protocol === "string" && source.otlp_protocol.trim()
          ? source.otlp_protocol.trim().toLowerCase()
          : defaultState.otlpProtocol,
      otlpHeadersEnv:
        typeof source.otlp_headers_env === "string" &&
        source.otlp_headers_env.trim()
          ? source.otlp_headers_env.trim()
          : defaultState.otlpHeadersEnv,
      langfusePublicKeyEnv:
        typeof source.langfuse_public_key_env === "string" &&
        source.langfuse_public_key_env.trim()
          ? source.langfuse_public_key_env.trim()
          : defaultState.langfusePublicKeyEnv,
      langfuseSecretKeyEnv:
        typeof source.langfuse_secret_key_env === "string" &&
        source.langfuse_secret_key_env.trim()
          ? source.langfuse_secret_key_env.trim()
          : defaultState.langfuseSecretKeyEnv,
      serviceName:
        typeof source.service_name === "string" && source.service_name.trim()
          ? source.service_name.trim()
          : defaultState.serviceName,
    };
    observabilityCache.set(configPath, { mtimeMs: stat.mtimeMs, settings });
    return settings;
  } catch {
    return defaultState;
  }
}

function parseHeaders(raw: string): Record<string, string> {
  const headers: Record<string, string> = {};
  let count = 0;
  for (const part of raw.split(",")) {
    if (count >= 32) {
      break;
    }
    const token = part.trim();
    if (!token) {
      continue;
    }
    const idx = token.indexOf("=");
    if (idx <= 0) {
      continue;
    }
    const key = token.slice(0, idx).trim();
    const value = token.slice(idx + 1).trim();
    const normalizedKey = key.toLowerCase();
    if (
      !/^[!#$%&'*+.^_`|~0-9A-Za-z-]{1,128}$/.test(key) ||
      !value ||
      value.length > 4096 ||
      /[\r\n]/.test(value) ||
      [
        "connection",
        "content-length",
        "content-type",
        "host",
        "transfer-encoding",
      ].includes(normalizedKey)
    ) {
      continue;
    }
    headers[key] = value;
    count += 1;
  }
  headers["content-type"] = "application/json";
  return headers;
}

function derivedLangfuseAuth(settings: ObservabilitySettings): string {
  const publicKey = process.env[settings.langfusePublicKeyEnv]?.trim() || "";
  const secretKey = process.env[settings.langfuseSecretKeyEnv]?.trim() || "";
  if (!publicKey || !secretKey) {
    return "";
  }
  const encoded = Buffer.from(`${publicKey}:${secretKey}`, "utf-8").toString(
    "base64",
  );
  return `Authorization=Basic ${encoded}`;
}

function resolveOtelEnvState(
  settings: ObservabilitySettings,
): OtelEnvCacheEntry {
  const explicitToggleRaw = process.env.MY_OPENCODE_OTEL_EXPORT_ENABLED;
  const tracesEndpointRaw = process.env.MY_OPENCODE_OTEL_EXPORT_TRACES_ENDPOINT;
  const defaultTracesEndpointRaw =
    process.env.OTEL_EXPORTER_OTLP_TRACES_ENDPOINT;
  const explicitHeadersRaw = process.env.MY_OPENCODE_OTEL_EXPORT_HEADERS;
  const headersEnvKey = settings.otlpHeadersEnv || "OTEL_EXPORTER_OTLP_HEADERS";
  const headersEnvRaw = process.env[headersEnvKey];
  const defaultHeadersRaw = process.env.OTEL_EXPORTER_OTLP_HEADERS;
  const langfusePublicKeyEnv = settings.langfusePublicKeyEnv;
  const langfuseSecretKeyEnv = settings.langfuseSecretKeyEnv;
  const langfusePublicKeyRaw = process.env[langfusePublicKeyEnv];
  const langfuseSecretKeyRaw = process.env[langfuseSecretKeyEnv];
  const timeoutRaw = process.env.MY_OPENCODE_OTEL_EXPORT_TIMEOUT_MS;
  const cached = otelEnvCache;
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
    return cached;
  }
  const explicitToggleParsed = explicitToggleRaw
    ? parseBool(explicitToggleRaw, false)
    : null;
  const rawHeaders =
    explicitHeadersRaw?.trim() ||
    headersEnvRaw?.trim() ||
    defaultHeadersRaw?.trim() ||
    (settings.provider === "langfuse" ? derivedLangfuseAuth(settings) : "");
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
    timeoutMs: parseBoundedInt(
      timeoutRaw,
      DEFAULT_OTLP_TIMEOUT_MS,
      MIN_OTLP_TIMEOUT_MS,
      MAX_OTLP_TIMEOUT_MS,
    ),
  };
  otelEnvCache = next;
  return next;
}

function validOtelEndpoint(raw: string): string | null {
  if (!raw || raw.length > 2048) {
    return null;
  }
  try {
    const parsed = new URL(raw);
    if (
      !["http:", "https:"].includes(parsed.protocol) ||
      parsed.username ||
      parsed.password
    ) {
      return null;
    }
    return parsed.toString();
  } catch {
    return null;
  }
}

function resolveOtelSink(directory: string): OtelSinkContext | null {
  const explicitEnvToggle = process.env.MY_OPENCODE_OTEL_EXPORT_ENABLED;
  if (explicitEnvToggle && !parseBool(explicitEnvToggle, false)) {
    return null;
  }
  const settings = loadObservabilitySettings(directory);
  const envState = resolveOtelEnvState(settings);
  if (!(envState.explicitToggleParsed ?? settings.enabled)) {
    return null;
  }
  if (
    !["langfuse", "otlp"].includes(settings.provider) ||
    settings.otlpProtocol !== "http/json"
  ) {
    return null;
  }
  const fetchFn = (globalThis as unknown as { fetch?: FetchLike }).fetch;
  if (!fetchFn || (!envState.rawHeaders && settings.provider === "langfuse")) {
    return null;
  }
  const endpoint = validOtelEndpoint(envState.tracesEndpoint);
  if (!endpoint) {
    return null;
  }
  const headers = Object.freeze({ ...parseHeaders(envState.rawHeaders) });
  return Object.freeze({
    endpoint,
    protocol: "http/json" as const,
    serviceName:
      sanitizeGatewayAuditText(settings.serviceName).slice(0, 128) ||
      "my_opencode",
    headers,
    timeoutMs: envState.timeoutMs,
    fetchFn,
  });
}

function normalizeSensitiveKey(key: string): string {
  return key
    .trim()
    .toLowerCase()
    .replace(/[.\s-]+/g, "_");
}

function isSensitiveAuditKey(key: string): boolean {
  const normalized = normalizeSensitiveKey(key);
  return (
    SENSITIVE_AUDIT_KEYS.has(normalized) ||
    /_(?:api_key|password|private_key|secret|token)$/.test(normalized)
  );
}

export function sanitizeGatewayAuditText(value: unknown): string {
  let text: string;
  try {
    text = String(value ?? "");
  } catch {
    return "[UNAVAILABLE]";
  }
  const redacted = text
    .replace(
      /\bauthorization\s*[:=]\s*[^\s,;]+(?:\s+[^\s,;]+)?/gi,
      "Authorization=[REDACTED]",
    )
    .replace(/\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]+/gi, "[REDACTED]")
    .replace(
      /\b(api[_-]?key|access[_-]?token|refresh[_-]?token|token|password|passwd|passphrase|secret)\b(\s*[:=]\s*)(?:"[^"]*"|'[^']*'|[^\s,;]+)/gi,
      (_match, key: string, separator: string) =>
        `${key}${separator}[REDACTED]`,
    )
    .replace(
      /\b(?:github_pat|ghp|gho|ghs|ghu|sk|rk|xoxb|xoxp|xoxa|xoxr)[-_][A-Za-z0-9_-]{8,}\b/gi,
      "[REDACTED]",
    );
  if (redacted.length <= MAX_AUDIT_STRING_CHARS) {
    return redacted;
  }
  return `${redacted.slice(0, MAX_AUDIT_STRING_CHARS)}…[TRUNCATED]`;
}

function sanitizeAuditValue(
  value: unknown,
  key: string,
  depth: number,
  state: SanitizerState,
): unknown {
  if (isSensitiveAuditKey(key)) {
    return "[REDACTED]";
  }
  if (state.remainingNodes <= 0) {
    return "[TRUNCATED]";
  }
  state.remainingNodes -= 1;
  if (value === null || typeof value === "boolean") {
    return value;
  }
  if (typeof value === "string") {
    return sanitizeGatewayAuditText(value);
  }
  if (typeof value === "number") {
    return Number.isFinite(value) ? value : String(value);
  }
  if (typeof value === "bigint") {
    return value.toString();
  }
  if (typeof value === "undefined") {
    return "[UNDEFINED]";
  }
  if (typeof value === "function" || typeof value === "symbol") {
    return "[UNSUPPORTED]";
  }
  if (depth >= MAX_AUDIT_DEPTH) {
    return "[TRUNCATED]";
  }
  if (!value || typeof value !== "object") {
    return sanitizeGatewayAuditText(value);
  }
  if (state.seen.has(value)) {
    return "[CIRCULAR]";
  }
  state.seen.add(value);
  try {
    if (Array.isArray(value)) {
      const result: unknown[] = [];
      const limit = Math.min(value.length, MAX_AUDIT_COLLECTION_ITEMS);
      for (let idx = 0; idx < limit; idx += 1) {
        let item: unknown = "[UNAVAILABLE]";
        try {
          const descriptor = Object.getOwnPropertyDescriptor(
            value,
            String(idx),
          );
          item =
            descriptor && "value" in descriptor
              ? descriptor.value
              : descriptor
                ? "[ACCESSOR]"
                : "[EMPTY]";
        } catch {
          item = "[UNAVAILABLE]";
        }
        result.push(sanitizeAuditValue(item, "", depth + 1, state));
      }
      if (value.length > limit) {
        result.push(`[TRUNCATED ${value.length - limit} ITEMS]`);
      }
      return result;
    }

    const result: Record<string, unknown> = Object.create(null) as Record<
      string,
      unknown
    >;
    const keys = Object.keys(value);
    const limit = Math.min(keys.length, MAX_AUDIT_COLLECTION_ITEMS);
    for (let idx = 0; idx < limit; idx += 1) {
      const rawKey = keys[idx] ?? "";
      const safeKey =
        sanitizeGatewayAuditText(rawKey).slice(0, MAX_AUDIT_KEY_CHARS) ||
        "[EMPTY_KEY]";
      let item: unknown = "[UNAVAILABLE]";
      try {
        const descriptor = Object.getOwnPropertyDescriptor(value, rawKey);
        item =
          descriptor && "value" in descriptor
            ? descriptor.value
            : descriptor
              ? "[ACCESSOR]"
              : "[UNAVAILABLE]";
      } catch {
        item = "[UNAVAILABLE]";
      }
      result[safeKey] = sanitizeAuditValue(item, rawKey, depth + 1, state);
    }
    if (keys.length > limit) {
      result.__truncated_items = keys.length - limit;
    }
    return result;
  } finally {
    state.seen.delete(value);
  }
}

function sanitizeAuditEntry(
  entry: Record<string, unknown>,
): Record<string, unknown> {
  try {
    const sanitized = sanitizeAuditValue(entry, "", 0, {
      remainingNodes: MAX_AUDIT_NODES,
      seen: new WeakSet<object>(),
    });
    if (
      sanitized &&
      typeof sanitized === "object" &&
      !Array.isArray(sanitized)
    ) {
      return sanitized as Record<string, unknown>;
    }
  } catch {
    // The minimal envelope below intentionally contains no caller-provided values.
  }
  return {
    hook: "gateway",
    stage: "audit",
    reason_code: "audit_sanitization_failed",
    sanitizer_error: true,
  };
}

function boundedAuditLine(payload: Record<string, unknown>): Buffer {
  const line = Buffer.from(`${JSON.stringify(payload)}\n`, "utf-8");
  if (line.byteLength <= MAX_AUDIT_RECORD_BYTES) {
    return line;
  }
  return Buffer.from(
    `${JSON.stringify({
      hook: "gateway",
      stage: "audit",
      reason_code: "audit_record_too_large",
      sanitizer_error: true,
      ts: payload.ts,
    })}\n`,
    "utf-8",
  );
}

function normalizeTraceId(value: unknown): string {
  const raw = String(value ?? "")
    .replace(/[^a-fA-F0-9]/g, "")
    .toLowerCase();
  if (raw.length === 32) {
    return raw;
  }
  if (raw.length > 32) {
    return raw.slice(0, 32);
  }
  return randomBytes(16).toString("hex");
}

function spanId(): string {
  return randomBytes(8).toString("hex");
}

function nowNanos(): string {
  return (BigInt(Date.now()) * 1_000_000n).toString();
}

function hashedSessionId(entry: Record<string, unknown>): string | null {
  for (const key of ["session_id", "sessionID", "sessionId"]) {
    const value = entry[key];
    if (typeof value === "string" && value.trim()) {
      return createHash("sha256").update(value, "utf-8").digest("hex");
    }
  }
  return null;
}

function allowlistedOtelEvent(
  entry: Record<string, unknown>,
): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  for (const key of OTLP_STRING_ATTRIBUTES) {
    const value = entry[key];
    if (typeof value === "string" && value) {
      result[key] = sanitizeGatewayAuditText(value).slice(
        0,
        MAX_OTLP_ATTRIBUTE_CHARS,
      );
    }
  }
  for (const key of OTLP_BOOLEAN_ATTRIBUTES) {
    const value = entry[key];
    if (typeof value === "boolean") {
      result[key] = value;
    }
  }
  for (const key of OTLP_NUMBER_ATTRIBUTES) {
    const value = entry[key];
    if (typeof value === "number" && Number.isFinite(value)) {
      result[key] = value;
    }
  }
  const sessionIdHash = hashedSessionId(entry);
  if (sessionIdHash) {
    result.session_id_hash = sessionIdHash;
  }
  return result;
}

function otelAttributes(
  entry: Record<string, unknown>,
): Array<Record<string, unknown>> {
  const attrs: Array<Record<string, unknown>> = [];
  for (const [key, value] of Object.entries(entry)) {
    if (typeof value === "string") {
      attrs.push({ key, value: { stringValue: value } });
    } else if (typeof value === "number") {
      attrs.push({ key, value: { doubleValue: value } });
    } else if (typeof value === "boolean") {
      attrs.push({ key, value: { boolValue: value } });
    }
  }
  return attrs;
}

function otelSpanPayload(
  serviceName: string,
  entry: Record<string, unknown>,
  traceId: string,
): Record<string, unknown> {
  const start = nowNanos();
  const end = nowNanos();
  const name = `${String(entry.hook ?? "gateway")}.${String(entry.reason_code ?? "event")}`;
  const isFailure = /(?:error|fail|blocked)/i.test(
    String(entry.reason_code ?? ""),
  );
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
                  code: isFailure ? 2 : 1,
                },
              },
            ],
          },
        ],
      },
    ],
  };
}

function prepareOtelBody(
  entry: Record<string, unknown>,
  sink: OtelSinkContext,
): string | null {
  const allowlisted = allowlistedOtelEvent(entry);
  const body = JSON.stringify(
    otelSpanPayload(
      sink.serviceName,
      allowlisted,
      normalizeTraceId(entry.trace_id),
    ),
  );
  if (Buffer.byteLength(body, "utf-8") > MAX_OTLP_BODY_BYTES) {
    return null;
  }
  return body;
}

function cancelResponseBody(response: unknown): void {
  if (!response || typeof response !== "object") {
    return;
  }
  const body = (response as { body?: { cancel?: () => unknown } }).body;
  if (body && typeof body.cancel === "function") {
    try {
      void Promise.resolve(body.cancel()).catch(() => undefined);
    } catch {
      // Response disposal is best-effort and must not stall the exporter.
    }
  }
}

function responseSucceeded(response: unknown): boolean {
  if (!response || typeof response !== "object") {
    return false;
  }
  const candidate = response as { ok?: unknown; status?: unknown };
  if (typeof candidate.status === "number") {
    return candidate.status >= 200 && candidate.status < 300;
  }
  return candidate.ok === true;
}

async function sendOtelJob(
  job: OtelExportJob,
  generation: number,
  controller: AbortController | undefined,
): Promise<void> {
  if (generation === otelGeneration) {
    otelStats.sent += 1;
  }

  type Outcome =
    | { kind: "response"; response: unknown }
    | { kind: "error" }
    | { kind: "timeout" };

  let resolveTimeout: ((outcome: Outcome) => void) | null = null;
  const timeoutPromise = new Promise<Outcome>((resolve) => {
    resolveTimeout = resolve;
  });
  const timer = setTimeout(() => {
    controller?.abort();
    resolveTimeout?.({ kind: "timeout" });
  }, job.sink.timeoutMs);
  activeOtelTimeout = timer;
  if (otelFlushWaiters.size > 0) {
    timer.ref?.();
  } else {
    timer.unref?.();
  }

  let requestPromise: Promise<Outcome>;
  try {
    requestPromise = Promise.resolve(
      job.sink.fetchFn(job.sink.endpoint, {
        method: "POST",
        headers: job.sink.headers,
        body: job.body,
        signal: controller?.signal,
      }),
    ).then(
      (response) => ({ kind: "response", response }) as Outcome,
      () => ({ kind: "error" }) as Outcome,
    );
  } catch {
    requestPromise = Promise.resolve({ kind: "error" });
  }

  const outcome = await Promise.race([requestPromise, timeoutPromise]);
  clearTimeout(timer);
  if (activeOtelTimeout === timer) {
    activeOtelTimeout = null;
  }
  if (generation !== otelGeneration) {
    return;
  }
  if (outcome.kind === "timeout") {
    otelStats.timedOut += 1;
    otelStats.failed += 1;
    return;
  }
  if (outcome.kind === "error") {
    otelStats.failed += 1;
    return;
  }
  cancelResponseBody(outcome.response);
  if (responseSucceeded(outcome.response)) {
    otelStats.succeeded += 1;
  } else {
    otelStats.httpFailures += 1;
    otelStats.failed += 1;
  }
}

function notifyOtelFlushWaiters(): void {
  if (otelInFlight || otelQueue.length > 0) {
    return;
  }
  for (const resolve of otelFlushWaiters) {
    resolve();
  }
  otelFlushWaiters.clear();
}

function drainOtelQueue(): void {
  if (otelInFlight) {
    return;
  }
  const job = otelQueue.shift();
  if (!job) {
    notifyOtelFlushWaiters();
    return;
  }
  const generation = otelGeneration;
  const controller =
    typeof AbortController !== "undefined" ? new AbortController() : undefined;
  activeOtelController = controller ?? null;
  otelInFlight = true;
  void sendOtelJob(job, generation, controller).finally(() => {
    if (generation !== otelGeneration) {
      return;
    }
    activeOtelController = null;
    otelInFlight = false;
    drainOtelQueue();
  });
}

function enqueueOtel(
  entry: Record<string, unknown>,
  sink: OtelSinkContext,
): boolean {
  const body = prepareOtelBody(entry, sink);
  if (!body) {
    otelStats.oversized += 1;
    return false;
  }
  const pendingCapacity = MAX_OTLP_QUEUE - (otelInFlight ? 1 : 0);
  while (otelQueue.length >= pendingCapacity) {
    otelQueue.shift();
    otelStats.dropped += 1;
  }
  otelQueue.push(Object.freeze({ body, sink }));
  otelStats.enqueued += 1;
  drainOtelQueue();
  return true;
}

export function gatewayEventAuditExportStatsForTest(): GatewayEventAuditExportStats {
  return {
    ...otelStats,
    queued: otelQueue.length,
    inFlight: otelInFlight ? 1 : 0,
  };
}

export function flushGatewayEventAuditExportsForTest(): Promise<void> {
  if (!otelInFlight && otelQueue.length === 0) {
    return Promise.resolve();
  }
  return new Promise<void>((resolve) => {
    otelFlushWaiters.add(resolve);
    activeOtelTimeout?.ref?.();
  });
}

export function resetGatewayEventAuditStateForTest(): void {
  otelGeneration += 1;
  activeOtelController?.abort();
  activeOtelController = null;
  activeOtelTimeout?.unref?.();
  activeOtelTimeout = null;
  otelQueue.splice(0, otelQueue.length);
  otelInFlight = false;
  otelStats = emptyOtelStats();
  localAggregateAuditGeneration += 1;
  localAggregateAuditQueue.splice(0, localAggregateAuditQueue.length);
  localAggregateAuditQueuedRecords = 0;
  localAggregateAuditScheduled = false;
  observabilityCache.clear();
  auditWriterCache.clear();
  auditEnvCache = null;
  otelEnvCache = null;
  notifyOtelFlushWaiters();
}

// Returns true when gateway event auditing is enabled.
export function gatewayEventAuditEnabled(): boolean {
  return resolveAuditEnvState().auditEnabled;
}

// Resolves gateway event audit file path.
export function gatewayEventAuditPath(directory: string): string {
  const state = resolveAuditEnvState();
  if (state.auditPathOverride) {
    return state.auditPathOverride;
  }
  return join(directory, ".opencode", "gateway-events.jsonl");
}

function currentUid(): number | null {
  return PROCESS_UID;
}

function assertOwnedByCurrentUser(state: Stats, label: string): void {
  const uid = currentUid();
  if (uid !== null && state.uid !== uid) {
    throw new Error(`${label} is not owned by the current user`);
  }
}

function ensurePrivateAuditDirectory(path: string): void {
  let created = false;
  let before: Stats;
  try {
    before = lstatSync(path);
  } catch (error) {
    if ((error as { code?: string }).code !== "ENOENT") {
      throw error;
    }
    mkdirSync(path, { recursive: true, mode: 0o700 });
    created = true;
    before = lstatSync(path);
  }
  if (!before.isDirectory() || before.isSymbolicLink()) {
    throw new Error("unsafe gateway audit directory");
  }
  assertOwnedByCurrentUser(before, "gateway audit directory");
  if (!(before.mode & 0o077)) {
    return;
  }
  if (!created && basename(path) !== ".opencode") {
    throw new Error("gateway audit directory is not owner-only");
  }
  const flags =
    constants.O_RDONLY |
    (constants.O_DIRECTORY ?? 0) |
    (constants.O_NOFOLLOW ?? 0);
  const descriptor = openSync(path, flags);
  try {
    const opened = fstatSync(descriptor);
    if (
      !opened.isDirectory() ||
      opened.dev !== before.dev ||
      opened.ino !== before.ino
    ) {
      throw new Error("gateway audit directory changed during validation");
    }
    assertOwnedByCurrentUser(opened, "gateway audit directory");
    fchmodSync(descriptor, 0o700);
  } finally {
    closeSync(descriptor);
  }
}

function safeAuditFileState(path: string): Stats | null {
  let state: Stats;
  try {
    state = lstatSync(path);
  } catch (error) {
    if ((error as { code?: string }).code === "ENOENT") {
      return null;
    }
    throw error;
  }
  if (!state.isFile() || state.isSymbolicLink() || state.nlink !== 1) {
    throw new Error("unsafe gateway audit file");
  }
  assertOwnedByCurrentUser(state, "gateway audit file");
  return state;
}

function openSafeExistingAuditFile(
  path: string,
  expected: Stats,
): OpenAuditFile {
  const flags =
    constants.O_WRONLY | constants.O_APPEND | (constants.O_NOFOLLOW ?? 0);
  const descriptor = openSync(path, flags);
  try {
    const opened = fstatSync(descriptor);
    if (
      !opened.isFile() ||
      opened.nlink !== 1 ||
      opened.dev !== expected.dev ||
      opened.ino !== expected.ino
    ) {
      throw new Error("gateway audit file changed during validation");
    }
    assertOwnedByCurrentUser(opened, "gateway audit file");
    return { descriptor, state: opened };
  } catch (error) {
    closeSync(descriptor);
    throw error;
  }
}

function openAuditAppendTarget(path: string): OpenAuditFile {
  const baseFlags =
    constants.O_WRONLY |
    constants.O_APPEND |
    (constants.O_NONBLOCK ?? 0) |
    (constants.O_NOFOLLOW ?? 0);
  let descriptor: number;
  try {
    descriptor = openSync(path, baseFlags);
  } catch (error) {
    if ((error as { code?: string }).code !== "ENOENT") {
      throw error;
    }
    try {
      descriptor = openSync(
        path,
        baseFlags | constants.O_CREAT | constants.O_EXCL,
        0o600,
      );
    } catch (createError) {
      if ((createError as { code?: string }).code !== "EEXIST") {
        throw createError;
      }
      descriptor = openSync(path, baseFlags);
    }
  }
  try {
    const state = fstatSync(descriptor);
    if (!state.isFile() || state.nlink !== 1) {
      throw new Error("unsafe opened gateway audit file");
    }
    assertOwnedByCurrentUser(state, "gateway audit file");
    if (state.mode & 0o077) {
      fchmodSync(descriptor, 0o600);
    }
    return { descriptor, state };
  } catch (error) {
    closeSync(descriptor);
    throw error;
  }
}

function makeAuditFilePrivate(path: string, state: Stats): void {
  const opened = openSafeExistingAuditFile(path, state);
  try {
    if (opened.state.mode & 0o077) {
      fchmodSync(opened.descriptor, 0o600);
    }
  } finally {
    closeSync(opened.descriptor);
  }
}

function rotateAudit(path: string, maxBackups: number): void {
  const states = new Map<number, Stats>();
  for (let idx = 0; idx <= maxBackups; idx += 1) {
    const candidate = idx === 0 ? path : `${path}.${idx}`;
    const state = safeAuditFileState(candidate);
    if (state) {
      states.set(idx, state);
    }
  }
  for (const [idx, state] of states) {
    makeAuditFilePrivate(idx === 0 ? path : `${path}.${idx}`, state);
  }
  if (states.has(maxBackups)) {
    unlinkSync(`${path}.${maxBackups}`);
  }
  for (let idx = maxBackups - 1; idx >= 1; idx -= 1) {
    if (states.has(idx)) {
      renameSync(`${path}.${idx}`, `${path}.${idx + 1}`);
    }
  }
  if (states.has(0)) {
    renameSync(path, `${path}.1`);
  }
}

function appendAuditLine(
  path: string,
  line: Buffer,
  maxBytes: number,
  maxBackups: number,
): void {
  ensurePrivateAuditDirectory(dirname(path));
  let opened = openAuditAppendTarget(path);
  if (opened.state.size + line.byteLength > maxBytes) {
    closeSync(opened.descriptor);
    rotateAudit(path, maxBackups);
    opened = openAuditAppendTarget(path);
  }
  try {
    const written = writeSync(
      opened.descriptor,
      line,
      0,
      line.byteLength,
      null,
    );
    if (written !== line.byteLength) {
      throw new Error("partial gateway audit write");
    }
  } finally {
    closeSync(opened.descriptor);
  }
}

function resolveAuditWriterState(key: string): AuditWriterState {
  const cached = auditWriterCache.get(key);
  if (cached) {
    return cached;
  }
  const state: AuditWriterState = {
    dedupeByKey: new Map<string, number>(),
  };
  auditWriterCache.set(key, state);
  return state;
}

function dedupeControls(entry: AuditWriteEntry): {
  key: string;
  windowMs: number;
} {
  try {
    const keyDescriptor = Object.getOwnPropertyDescriptor(
      entry,
      "audit_dedupe_key",
    );
    const windowDescriptor = Object.getOwnPropertyDescriptor(
      entry,
      "audit_dedupe_window_ms",
    );
    const keyValue =
      keyDescriptor && "value" in keyDescriptor
        ? keyDescriptor.value
        : undefined;
    const windowValue =
      windowDescriptor && "value" in windowDescriptor
        ? windowDescriptor.value
        : undefined;
    const rawKey =
      typeof keyValue === "string" && keyValue.trim() ? keyValue.trim() : "";
    const rawWindow = Number(windowValue);
    const windowMs =
      Number.isFinite(rawWindow) && rawWindow > 0
        ? Math.min(rawWindow, 24 * 60 * 60 * 1000)
        : 0;
    const key = rawKey
      ? createHash("sha256")
          .update(rawKey.slice(0, 4096), "utf-8")
          .digest("hex")
      : "";
    return { key, windowMs };
  } catch {
    return { key: "", windowMs: 0 };
  }
}

function sanitizedAuditPayload(
  entry: Record<string, unknown>,
): Record<string, unknown> {
  const sanitized = sanitizeAuditEntry(entry);
  delete sanitized.audit_dedupe_key;
  delete sanitized.audit_dedupe_window_ms;
  return {
    ...sanitized,
    ts: new Date().toISOString(),
  };
}

function appendLocalAggregateAudit(
  directory: string,
  entry: Readonly<Record<string, unknown>>,
): boolean {
  try {
    const auditState = resolveAuditEnvState();
    if (!auditState.auditEnabled) {
      return false;
    }
    const path = auditState.auditPathOverride
      ? auditState.auditPathOverride
      : join(directory, ".opencode", "gateway-events.jsonl");
    appendAuditLine(
      path,
      boundedAuditLine(sanitizedAuditPayload({ ...entry })),
      auditState.maxBytes,
      auditState.maxBackups,
    );
    return true;
  } catch {
    // Aggregate audit remains best-effort and isolated from hook dispatch.
    return false;
  }
}

function drainOneLocalAggregateAuditRecord(): void {
  const batch = localAggregateAuditQueue[0];
  if (!batch) {
    return;
  }
  const entry = batch.entries[batch.nextIndex];
  if (entry) {
    batch.succeeded =
      appendLocalAggregateAudit(batch.directory, entry) && batch.succeeded;
    batch.nextIndex += 1;
    localAggregateAuditQueuedRecords = Math.max(
      0,
      localAggregateAuditQueuedRecords - 1,
    );
  }
  if (batch.nextIndex >= batch.entries.length) {
    localAggregateAuditQueue.shift();
    try {
      batch.complete(batch.succeeded);
    } catch {
      // Completion acknowledgement is an isolation boundary.
    }
  }
}

function scheduleLocalAggregateAuditDrain(): void {
  if (localAggregateAuditScheduled || localAggregateAuditQueue.length === 0) {
    return;
  }
  localAggregateAuditScheduled = true;
  const generation = localAggregateAuditGeneration;
  const handle = setImmediate(() => {
    if (generation !== localAggregateAuditGeneration) {
      return;
    }
    localAggregateAuditScheduled = false;
    drainOneLocalAggregateAuditRecord();
    scheduleLocalAggregateAuditDrain();
  });
  handle.unref?.();
}

/** Queues an all-or-none local-only aggregate audit batch without OTLP export. */
export function enqueueGatewayLocalAggregateAudit(
  directory: string,
  entries: readonly Record<string, unknown>[],
  complete: (success: boolean) => void,
): boolean {
  try {
    if (entries.length === 0) {
      return true;
    }
    if (
      !gatewayEventAuditEnabled() ||
      entries.length > MAX_LOCAL_AGGREGATE_AUDIT_QUEUE ||
      localAggregateAuditQueuedRecords + entries.length >
        MAX_LOCAL_AGGREGATE_AUDIT_QUEUE
    ) {
      return false;
    }
    const allowedEntries = entries.map((entry) => {
      const allowedEntry = Object.fromEntries(
        Object.entries(entry).filter(([key]) =>
          LOCAL_AGGREGATE_AUDIT_KEYS.has(key),
        ),
      );
      return Object.freeze(allowedEntry);
    });
    localAggregateAuditQueue.push({
      directory,
      entries: allowedEntries,
      nextIndex: 0,
      succeeded: true,
      complete,
    });
    localAggregateAuditQueuedRecords += entries.length;
    scheduleLocalAggregateAuditDrain();
    return true;
  } catch {
    return false;
  }
}

/** Flushes queued local aggregate audit records synchronously for tests only. */
export function flushGatewayLocalAggregateAuditForTest(): void {
  localAggregateAuditGeneration += 1;
  localAggregateAuditScheduled = false;
  while (localAggregateAuditQueue.length > 0) {
    drainOneLocalAggregateAuditRecord();
  }
}

export function gatewayLocalAggregateAuditQueueSizeForTest(): number {
  return localAggregateAuditQueuedRecords;
}

// Appends one bounded, sanitized gateway event audit entry without surfacing sink failures.
export function writeGatewayEventAudit(
  directory: string,
  entry: Record<string, unknown>,
): void {
  try {
    const auditState = resolveAuditEnvState();
    const fileAuditEnabled = auditState.auditEnabled;
    const otelSink = resolveOtelSink(directory);
    if (!fileAuditEnabled && !otelSink) {
      return;
    }

    const path = auditState.auditPathOverride
      ? auditState.auditPathOverride
      : join(directory, ".opencode", "gateway-events.jsonl");
    const writerState = resolveAuditWriterState(
      fileAuditEnabled ? path : `otel:${directory}`,
    );
    const controls = dedupeControls(entry as AuditWriteEntry);
    if (controls.key && controls.windowMs > 0) {
      const previousTs = writerState.dedupeByKey.get(controls.key) ?? 0;
      if (Date.now() - previousTs < controls.windowMs) {
        return;
      }
    }

    const payload = sanitizedAuditPayload(entry);

    let accepted = false;
    if (fileAuditEnabled) {
      try {
        appendAuditLine(
          path,
          boundedAuditLine(payload),
          auditState.maxBytes,
          auditState.maxBackups,
        );
        accepted = true;
      } catch {
        // Local audit is best-effort and must never alter hook behavior.
      }
    }
    if (otelSink && enqueueOtel(payload, otelSink)) {
      accepted = true;
    }
    if (accepted && controls.key && controls.windowMs > 0) {
      writerState.dedupeByKey.set(controls.key, Date.now());
    }
  } catch {
    // Audit and telemetry are isolation boundaries, never hook failure sources.
  }
}

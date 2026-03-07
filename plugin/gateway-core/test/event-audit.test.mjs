import assert from "node:assert/strict"
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"

test("gateway event audit writes dispatch entries when enabled", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-event-audit-"))
  const previous = process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
  process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = "1"
  try {
    const plugin = GatewayCorePlugin({ directory, config: {} })
    await plugin.event({ event: { type: "session.idle", properties: {} } })

    const auditPath = join(directory, ".opencode", "gateway-events.jsonl")
    const lines = readFileSync(auditPath, "utf-8")
      .split(/\r?\n/)
      .filter(Boolean)
    assert.ok(lines.length >= 1)
    const first = JSON.parse(lines[0])
    assert.equal(first.reason_code, "event_dispatch")
    assert.equal(first.event_type, "session.idle")
  } finally {
    if (previous === undefined) {
      delete process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
    } else {
      process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = previous
    }
    rmSync(directory, { recursive: true, force: true })
  }
})

test("gateway event audit samples noisy dispatch events", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-event-audit-"))
  const previousEnabled = process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
  const previousRate = process.env.MY_OPENCODE_GATEWAY_DISPATCH_SAMPLE_RATE
  process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = "1"
  process.env.MY_OPENCODE_GATEWAY_DISPATCH_SAMPLE_RATE = "5"
  try {
    const plugin = GatewayCorePlugin({ directory, config: {} })
    for (let i = 0; i < 6; i += 1) {
      await plugin.event({ event: { type: "session.updated", properties: { i } } })
    }
    const auditPath = join(directory, ".opencode", "gateway-events.jsonl")
    const events = readFileSync(auditPath, "utf-8")
      .split(/\r?\n/)
      .filter(Boolean)
      .map((line) => JSON.parse(line))
      .filter(
        (event) =>
          event.reason_code === "event_dispatch" &&
          event.event_type === "session.updated",
      )
    assert.equal(events.length, 2)
  } finally {
    if (previousEnabled === undefined) {
      delete process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
    } else {
      process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = previousEnabled
    }
    if (previousRate === undefined) {
      delete process.env.MY_OPENCODE_GATEWAY_DISPATCH_SAMPLE_RATE
    } else {
      process.env.MY_OPENCODE_GATEWAY_DISPATCH_SAMPLE_RATE = previousRate
    }
    rmSync(directory, { recursive: true, force: true })
  }
})


test("gateway event audit rotates file when max bytes threshold is exceeded", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-event-audit-"))
  const previousEnabled = process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
  const previousMax = process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT_MAX_BYTES
  const previousBackups = process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT_MAX_BACKUPS
  process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = "1"
  process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT_MAX_BYTES = "200"
  process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT_MAX_BACKUPS = "2"
  try {
    const plugin = GatewayCorePlugin({ directory, config: {} })
    for (let i = 0; i < 10; i += 1) {
      await plugin.event({ event: { type: "session.idle", properties: { i } } })
    }
    const base = join(directory, ".opencode", "gateway-events.jsonl")
    const rotated = `${base}.1`
    const baseLines = readFileSync(base, "utf-8").split(/\r?\n/).filter(Boolean)
    const rotatedLines = readFileSync(rotated, "utf-8").split(/\r?\n/).filter(Boolean)
    assert.ok(baseLines.length >= 1)
    assert.ok(rotatedLines.length >= 1)
  } finally {
    if (previousEnabled === undefined) {
      delete process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
    } else {
      process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = previousEnabled
    }
    if (previousMax === undefined) {
      delete process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT_MAX_BYTES
    } else {
      process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT_MAX_BYTES = previousMax
    }
    if (previousBackups === undefined) {
      delete process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT_MAX_BACKUPS
    } else {
      process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT_MAX_BACKUPS = previousBackups
    }
    rmSync(directory, { recursive: true, force: true })
  }
})

test("gateway event audit exports OTLP span when observability enabled", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-event-audit-"))
  const previousEnabled = process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
  const previousOtel = process.env.MY_OPENCODE_OTEL_EXPORT_ENABLED
  const previousHeaders = process.env.OTEL_EXPORTER_OTLP_HEADERS
  const previousConfigPath = process.env.OPENCODE_CONFIG_PATH
  const originalFetch = globalThis.fetch

  process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = "1"
  process.env.MY_OPENCODE_OTEL_EXPORT_ENABLED = "1"
  process.env.OTEL_EXPORTER_OTLP_HEADERS = "Authorization=Basic test"
  delete process.env.OPENCODE_CONFIG_PATH

  const requests = []
  globalThis.fetch = async (url, init) => {
    requests.push({ url, init })
    return { ok: true, status: 200, text: async () => "ok" }
  }

  writeFileSync(
    join(directory, "opencode.json"),
    JSON.stringify({
      observability: {
        enabled: true,
        provider: "langfuse",
        otlp_traces_endpoint: "http://localhost:3005/api/public/otel/v1/traces",
        otlp_protocol: "http/json",
        service_name: "my_opencode-test",
      },
    }),
    "utf-8",
  )

  try {
    const plugin = GatewayCorePlugin({ directory, config: {} })
    await plugin.event({ event: { type: "session.idle", properties: { probe: true } } })

    assert.ok(requests.length >= 1)
    assert.equal(requests[0].url, "http://localhost:3005/api/public/otel/v1/traces")
    const body = JSON.parse(String(requests[0].init?.body ?? "{}"))
    const spans = body?.resourceSpans?.[0]?.scopeSpans?.[0]?.spans ?? []
    assert.ok(Array.isArray(spans) && spans.length >= 1)
    assert.equal(typeof spans[0].traceId, "string")
    assert.equal(spans[0].traceId.length, 32)
  } finally {
    if (previousEnabled === undefined) {
      delete process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
    } else {
      process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = previousEnabled
    }
    if (previousOtel === undefined) {
      delete process.env.MY_OPENCODE_OTEL_EXPORT_ENABLED
    } else {
      process.env.MY_OPENCODE_OTEL_EXPORT_ENABLED = previousOtel
    }
    if (previousHeaders === undefined) {
      delete process.env.OTEL_EXPORTER_OTLP_HEADERS
    } else {
      process.env.OTEL_EXPORTER_OTLP_HEADERS = previousHeaders
    }
    if (previousConfigPath === undefined) {
      delete process.env.OPENCODE_CONFIG_PATH
    } else {
      process.env.OPENCODE_CONFIG_PATH = previousConfigPath
    }
    globalThis.fetch = originalFetch
    rmSync(directory, { recursive: true, force: true })
  }
})

test("gateway event audit derives OTLP auth header from Langfuse keys", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-event-audit-"))
  const previousEnabled = process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
  const previousOtel = process.env.MY_OPENCODE_OTEL_EXPORT_ENABLED
  const previousHeaders = process.env.OTEL_EXPORTER_OTLP_HEADERS
  const previousPublic = process.env.LANGFUSE_PUBLIC_KEY
  const previousSecret = process.env.LANGFUSE_SECRET_KEY
  const previousConfigPath = process.env.OPENCODE_CONFIG_PATH
  const originalFetch = globalThis.fetch

  process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = "1"
  process.env.MY_OPENCODE_OTEL_EXPORT_ENABLED = "1"
  process.env.LANGFUSE_PUBLIC_KEY = "pk-lf-test"
  process.env.LANGFUSE_SECRET_KEY = "sk-lf-test"
  delete process.env.OTEL_EXPORTER_OTLP_HEADERS
  delete process.env.OPENCODE_CONFIG_PATH

  const requests = []
  globalThis.fetch = async (url, init) => {
    requests.push({ url, init })
    return { ok: true, status: 200, text: async () => "ok" }
  }

  writeFileSync(
    join(directory, "opencode.json"),
    JSON.stringify({
      observability: {
        enabled: true,
        provider: "langfuse",
        otlp_traces_endpoint: "http://localhost:3005/api/public/otel/v1/traces",
      },
    }),
    "utf-8",
  )

  try {
    const plugin = GatewayCorePlugin({ directory, config: {} })
    await plugin.event({ event: { type: "session.idle", properties: { probe: "keys" } } })

    assert.ok(requests.length >= 1)
    const headers = requests[0].init?.headers ?? {}
    const auth = headers.Authorization || headers.authorization || ""
    assert.ok(String(auth).startsWith("Basic "))
  } finally {
    if (previousEnabled === undefined) {
      delete process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
    } else {
      process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = previousEnabled
    }
    if (previousOtel === undefined) {
      delete process.env.MY_OPENCODE_OTEL_EXPORT_ENABLED
    } else {
      process.env.MY_OPENCODE_OTEL_EXPORT_ENABLED = previousOtel
    }
    if (previousHeaders === undefined) {
      delete process.env.OTEL_EXPORTER_OTLP_HEADERS
    } else {
      process.env.OTEL_EXPORTER_OTLP_HEADERS = previousHeaders
    }
    if (previousPublic === undefined) {
      delete process.env.LANGFUSE_PUBLIC_KEY
    } else {
      process.env.LANGFUSE_PUBLIC_KEY = previousPublic
    }
    if (previousSecret === undefined) {
      delete process.env.LANGFUSE_SECRET_KEY
    } else {
      process.env.LANGFUSE_SECRET_KEY = previousSecret
    }
    if (previousConfigPath === undefined) {
      delete process.env.OPENCODE_CONFIG_PATH
    } else {
      process.env.OPENCODE_CONFIG_PATH = previousConfigPath
    }
    globalThis.fetch = originalFetch
    rmSync(directory, { recursive: true, force: true })
  }
})

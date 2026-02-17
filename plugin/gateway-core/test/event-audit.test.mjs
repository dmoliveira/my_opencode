import assert from "node:assert/strict"
import { mkdtempSync, readFileSync, rmSync } from "node:fs"
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

import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import {
  existsSync,
  linkSync,
  lstatSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import {
  flushGatewayEventAuditExportsForTest,
  gatewayEventAuditExportStatsForTest,
  resetGatewayEventAuditStateForTest,
  writeGatewayEventAudit,
} from "../dist/audit/event-audit.js";

const inheritedOtelToggle = process.env.MY_OPENCODE_OTEL_EXPORT_ENABLED;

test.beforeEach(() => {
  resetGatewayEventAuditStateForTest();
  process.env.MY_OPENCODE_OTEL_EXPORT_ENABLED = "0";
});

test.afterEach(async () => {
  await flushGatewayEventAuditExportsForTest();
  resetGatewayEventAuditStateForTest();
  if (inheritedOtelToggle === undefined) {
    delete process.env.MY_OPENCODE_OTEL_EXPORT_ENABLED;
  } else {
    process.env.MY_OPENCODE_OTEL_EXPORT_ENABLED = inheritedOtelToggle;
  }
});

test("gateway event audit sanitizes bounded records and owns timestamps", () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-event-audit-safe-"));
  const previousEnabled = process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT;
  process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = "1";
  try {
    const circular = { safe: "retained" };
    circular.self = circular;
    let getterReads = 0;
    const accessor = {};
    Object.defineProperty(accessor, "safe", {
      enumerable: true,
      get() {
        getterReads += 1;
        return "getter-canary";
      },
    });
    writeGatewayEventAudit(directory, {
      hook: "test",
      reason_code: "security_probe",
      ts: "spoofed-timestamp",
      authorization: "Authorization=Basic authorization-canary",
      error_message: "error-canary",
      command: "command-canary",
      message: "message-canary",
      detail: "Bearer bearer-canary api_key=api-key-canary token=token-canary",
      circular,
      accessor,
      long_detail: "x".repeat(10_000),
      collection: Array.from({ length: 100 }, (_, index) => index),
    });

    const hostile = new Proxy(
      {},
      {
        ownKeys() {
          throw new Error("hostile-own-keys-canary");
        },
      },
    );
    writeGatewayEventAudit(directory, hostile);

    const auditPath = join(directory, ".opencode", "gateway-events.jsonl");
    const raw = readFileSync(auditPath, "utf-8");
    for (const canary of [
      "authorization-canary",
      "error-canary",
      "command-canary",
      "message-canary",
      "bearer-canary",
      "api-key-canary",
      "token-canary",
      "hostile-own-keys-canary",
      "getter-canary",
      "spoofed-timestamp",
    ]) {
      assert.equal(
        raw.includes(canary),
        false,
        `unexpected persisted canary: ${canary}`,
      );
    }

    const entries = raw
      .split(/\r?\n/)
      .filter(Boolean)
      .map((line) => JSON.parse(line));
    assert.equal(entries[0]?.authorization, "[REDACTED]");
    assert.equal(entries[0]?.error_message, "[REDACTED]");
    assert.equal(entries[0]?.command, "[REDACTED]");
    assert.equal(entries[0]?.message, "[REDACTED]");
    assert.equal(entries[0]?.circular?.self, "[CIRCULAR]");
    assert.equal(entries[0]?.accessor?.safe, "[ACCESSOR]");
    assert.equal(getterReads, 0);
    assert.match(entries[0]?.long_detail ?? "", /\[TRUNCATED\]$/);
    assert.match(entries[0]?.collection?.at(-1) ?? "", /TRUNCATED 36 ITEMS/);
    assert.equal(entries[1]?.reason_code, "audit_sanitization_failed");
    assert.equal(lstatSync(auditPath).mode & 0o777, 0o600);
    assert.equal(lstatSync(join(directory, ".opencode")).mode & 0o777, 0o700);
  } finally {
    if (previousEnabled === undefined) {
      delete process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT;
    } else {
      process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = previousEnabled;
    }
    rmSync(directory, { recursive: true, force: true });
  }
});

test("gateway event audit rejects symlink, hard-link, and symlink-parent targets", () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-event-audit-unsafe-"));
  const targetDirectory = mkdtempSync(
    join(tmpdir(), "gateway-event-audit-target-"),
  );
  const previousEnabled = process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT;
  const previousMax = process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT_MAX_BYTES;
  process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = "1";
  try {
    const opencodeDirectory = join(directory, ".opencode");
    mkdirSync(opencodeDirectory, { mode: 0o700 });
    const auditPath = join(opencodeDirectory, "gateway-events.jsonl");

    const symlinkVictim = join(directory, "symlink-victim.txt");
    writeFileSync(symlinkVictim, "symlink-victim", "utf-8");
    symlinkSync(symlinkVictim, auditPath);
    writeGatewayEventAudit(directory, { hook: "test", reason_code: "symlink" });
    assert.equal(readFileSync(symlinkVictim, "utf-8"), "symlink-victim");
    assert.equal(lstatSync(auditPath).isSymbolicLink(), true);
    rmSync(auditPath, { force: true });

    const hardLinkVictim = join(directory, "hard-link-victim.txt");
    writeFileSync(hardLinkVictim, "hard-link-victim", "utf-8");
    linkSync(hardLinkVictim, auditPath);
    writeGatewayEventAudit(directory, {
      hook: "test",
      reason_code: "hard-link",
    });
    assert.equal(readFileSync(hardLinkVictim, "utf-8"), "hard-link-victim");
    assert.equal(lstatSync(hardLinkVictim).nlink, 2);
    rmSync(auditPath, { force: true });

    writeGatewayEventAudit(directory, {
      hook: "test",
      reason_code: "safe-base",
    });
    const safeBase = readFileSync(auditPath, "utf-8");
    const rotationVictim = join(directory, "rotation-victim.txt");
    writeFileSync(rotationVictim, "rotation-victim", "utf-8");
    symlinkSync(rotationVictim, `${auditPath}.1`);
    process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT_MAX_BYTES = "1";
    writeGatewayEventAudit(directory, {
      hook: "test",
      reason_code: "unsafe-rotation",
    });
    assert.equal(readFileSync(auditPath, "utf-8"), safeBase);
    assert.equal(readFileSync(rotationVictim, "utf-8"), "rotation-victim");
    assert.equal(lstatSync(`${auditPath}.1`).isSymbolicLink(), true);

    const parentDirectory = mkdtempSync(
      join(tmpdir(), "gateway-event-audit-parent-"),
    );
    const linkedParent = join(parentDirectory, ".opencode");
    symlinkSync(targetDirectory, linkedParent, "dir");
    writeGatewayEventAudit(parentDirectory, {
      hook: "test",
      reason_code: "parent-symlink",
    });
    assert.equal(
      existsSync(join(targetDirectory, "gateway-events.jsonl")),
      false,
    );
    rmSync(parentDirectory, { recursive: true, force: true });
  } finally {
    if (previousEnabled === undefined) {
      delete process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT;
    } else {
      process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = previousEnabled;
    }
    if (previousMax === undefined) {
      delete process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT_MAX_BYTES;
    } else {
      process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT_MAX_BYTES = previousMax;
    }
    rmSync(directory, { recursive: true, force: true });
    rmSync(targetDirectory, { recursive: true, force: true });
  }
});

test("gateway event audit keeps active and rotated files owner-only", () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-event-audit-modes-"));
  const previousEnabled = process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT;
  const previousMax = process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT_MAX_BYTES;
  process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = "1";
  process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT_MAX_BYTES = "200";
  try {
    for (let index = 0; index < 3; index += 1) {
      writeGatewayEventAudit(directory, {
        hook: "test",
        reason_code: `rotation-${index}`,
        detail: "x".repeat(120),
      });
    }
    const auditPath = join(directory, ".opencode", "gateway-events.jsonl");
    assert.equal(lstatSync(auditPath).mode & 0o777, 0o600);
    assert.equal(lstatSync(`${auditPath}.1`).mode & 0o777, 0o600);
  } finally {
    if (previousEnabled === undefined) {
      delete process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT;
    } else {
      process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = previousEnabled;
    }
    if (previousMax === undefined) {
      delete process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT_MAX_BYTES;
    } else {
      process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT_MAX_BYTES = previousMax;
    }
    rmSync(directory, { recursive: true, force: true });
  }
});

test("gateway event audit exports only allowlisted sanitized OTLP metadata", async () => {
  const directory = mkdtempSync(
    join(tmpdir(), "gateway-event-audit-otel-safe-"),
  );
  const previousEnabled = process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT;
  const previousHeaders = process.env.MY_OPENCODE_OTEL_EXPORT_HEADERS;
  const previousConfigPath = process.env.OPENCODE_CONFIG_PATH;
  const originalFetch = globalThis.fetch;
  const configPath = join(directory, "opencode.json");
  process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = "1";
  process.env.MY_OPENCODE_OTEL_EXPORT_ENABLED = "1";
  process.env.MY_OPENCODE_OTEL_EXPORT_HEADERS =
    "Authorization=Basic transport-secret";
  process.env.OPENCODE_CONFIG_PATH = configPath;
  writeFileSync(
    configPath,
    JSON.stringify({
      observability: {
        enabled: true,
        provider: "otlp",
        otlp_traces_endpoint: "http://localhost:4318/v1/traces",
        service_name: "audit-security-test",
      },
    }),
  );
  const requests = [];
  globalThis.fetch = async (url, init) => {
    requests.push({ url, init });
    return { ok: true, status: 200, body: { cancel: async () => undefined } };
  };
  try {
    writeGatewayEventAudit(directory, {
      hook: "test-hook",
      stage: "dispatch",
      reason_code: "security_probe",
      event_type: "tool.execute.after",
      session_id: "raw-session-canary",
      command: "command-canary",
      message: "message-canary",
      error_message: "error-canary",
      detail: "Authorization=Basic authorization-canary",
      nested: { token: "nested-token-canary" },
      hook_count: 3,
      critical: false,
      cacheable_system_prefix_sha256: "cache-fingerprint-canary",
      prompt_cache_strategy: "cache-strategy-canary",
      prompt_cache_shard_count: 1,
      prompt_cache_shard: 0,
    });
    await flushGatewayEventAuditExportsForTest();

    assert.equal(requests.length, 1);
    const requestBody = String(requests[0].init?.body ?? "");
    const localBody = readFileSync(
      join(directory, ".opencode", "gateway-events.jsonl"),
      "utf-8",
    );
    for (const canary of [
      "raw-session-canary",
      "command-canary",
      "message-canary",
      "error-canary",
      "authorization-canary",
      "nested-token-canary",
      "cache-fingerprint-canary",
      "cache-strategy-canary",
    ]) {
      assert.equal(
        requestBody.includes(canary),
        false,
        `unexpected OTLP canary: ${canary}`,
      );
    }
    assert.equal(localBody.includes("cache-fingerprint-canary"), true);
    assert.equal(localBody.includes("cache-strategy-canary"), true);
    for (const canary of [
      "command-canary",
      "message-canary",
      "error-canary",
      "authorization-canary",
      "nested-token-canary",
    ]) {
      assert.equal(
        localBody.includes(canary),
        false,
        `unexpected local canary: ${canary}`,
      );
    }

    const body = JSON.parse(requestBody);
    const attributes = body.resourceSpans[0].scopeSpans[0].spans[0].attributes;
    const keys = new Set(attributes.map((attribute) => attribute.key));
    assert.equal(keys.has("hook"), true);
    assert.equal(keys.has("reason_code"), true);
    assert.equal(keys.has("hook_count"), true);
    assert.equal(keys.has("session_id_hash"), true);
    assert.equal(keys.has("session_id"), false);
    assert.equal(keys.has("command"), false);
    assert.equal(keys.has("message"), false);
    assert.equal(keys.has("error_message"), false);
    assert.equal(keys.has("nested"), false);
    assert.equal(keys.has("cacheable_system_prefix_sha256"), false);
    assert.equal(keys.has("prompt_cache_strategy"), false);
    assert.equal(keys.has("prompt_cache_shard_count"), false);
    assert.equal(keys.has("prompt_cache_shard"), false);
    assert.equal(
      requests[0].init?.headers?.["content-type"],
      "application/json",
    );
    assert.equal(
      JSON.stringify(gatewayEventAuditExportStatsForTest()).includes(
        "transport-secret",
      ),
      false,
    );
  } finally {
    if (previousEnabled === undefined) {
      delete process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT;
    } else {
      process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = previousEnabled;
    }
    if (previousHeaders === undefined) {
      delete process.env.MY_OPENCODE_OTEL_EXPORT_HEADERS;
    } else {
      process.env.MY_OPENCODE_OTEL_EXPORT_HEADERS = previousHeaders;
    }
    if (previousConfigPath === undefined) {
      delete process.env.OPENCODE_CONFIG_PATH;
    } else {
      process.env.OPENCODE_CONFIG_PATH = previousConfigPath;
    }
    globalThis.fetch = originalFetch;
    rmSync(directory, { recursive: true, force: true });
  }
});

test("gateway event audit disables export for explicit protobuf protocol", async () => {
  const directory = mkdtempSync(
    join(tmpdir(), "gateway-event-audit-protobuf-"),
  );
  const previousConfigPath = process.env.OPENCODE_CONFIG_PATH;
  const originalFetch = globalThis.fetch;
  const configPath = join(directory, "opencode.json");
  process.env.MY_OPENCODE_OTEL_EXPORT_ENABLED = "1";
  process.env.OPENCODE_CONFIG_PATH = configPath;
  writeFileSync(
    configPath,
    JSON.stringify({
      observability: {
        enabled: true,
        provider: "otlp",
        otlp_protocol: "http/protobuf",
        otlp_traces_endpoint: "http://localhost:4318/v1/traces",
      },
    }),
  );
  let requestCount = 0;
  globalThis.fetch = async () => {
    requestCount += 1;
    return { ok: true, status: 200 };
  };
  try {
    writeGatewayEventAudit(directory, {
      hook: "test",
      reason_code: "protobuf-disabled",
    });
    await flushGatewayEventAuditExportsForTest();
    assert.equal(requestCount, 0);
    assert.equal(gatewayEventAuditExportStatsForTest().enqueued, 0);
  } finally {
    if (previousConfigPath === undefined) {
      delete process.env.OPENCODE_CONFIG_PATH;
    } else {
      process.env.OPENCODE_CONFIG_PATH = previousConfigPath;
    }
    globalThis.fetch = originalFetch;
    rmSync(directory, { recursive: true, force: true });
  }
});

test("gateway event audit snapshots sink context for queued exports", async () => {
  const directoryA = mkdtempSync(join(tmpdir(), "gateway-event-audit-sink-a-"));
  const directoryB = mkdtempSync(join(tmpdir(), "gateway-event-audit-sink-b-"));
  const previousConfigPath = process.env.OPENCODE_CONFIG_PATH;
  const previousHeaders = process.env.MY_OPENCODE_OTEL_EXPORT_HEADERS;
  const originalFetch = globalThis.fetch;
  const configA = join(directoryA, "opencode.json");
  const configB = join(directoryB, "opencode.json");
  writeFileSync(
    configA,
    JSON.stringify({
      observability: {
        enabled: true,
        provider: "otlp",
        otlp_traces_endpoint: "http://localhost:4318/a/v1/traces",
      },
    }),
  );
  writeFileSync(
    configB,
    JSON.stringify({
      observability: {
        enabled: true,
        provider: "otlp",
        otlp_traces_endpoint: "http://localhost:4318/b/v1/traces",
      },
    }),
  );
  process.env.MY_OPENCODE_OTEL_EXPORT_ENABLED = "1";
  const requests = [];
  let resolveFirst;
  globalThis.fetch = (url, init) => {
    requests.push({ url, init });
    if (requests.length === 1) {
      return new Promise((resolve) => {
        resolveFirst = () => resolve({ ok: true, status: 200 });
      });
    }
    return Promise.resolve({ ok: true, status: 200 });
  };
  try {
    process.env.OPENCODE_CONFIG_PATH = configA;
    process.env.MY_OPENCODE_OTEL_EXPORT_HEADERS = "X-Sink=A";
    writeGatewayEventAudit(directoryA, { hook: "test", reason_code: "sink-a" });

    process.env.OPENCODE_CONFIG_PATH = configB;
    process.env.MY_OPENCODE_OTEL_EXPORT_HEADERS = "X-Sink=B";
    writeGatewayEventAudit(directoryB, { hook: "test", reason_code: "sink-b" });
    assert.equal(requests.length, 1);
    resolveFirst();
    await flushGatewayEventAuditExportsForTest();

    assert.equal(requests.length, 2);
    assert.equal(requests[0].url, "http://localhost:4318/a/v1/traces");
    assert.equal(requests[0].init?.headers?.["X-Sink"], "A");
    assert.equal(requests[1].url, "http://localhost:4318/b/v1/traces");
    assert.equal(requests[1].init?.headers?.["X-Sink"], "B");
  } finally {
    if (previousConfigPath === undefined) {
      delete process.env.OPENCODE_CONFIG_PATH;
    } else {
      process.env.OPENCODE_CONFIG_PATH = previousConfigPath;
    }
    if (previousHeaders === undefined) {
      delete process.env.MY_OPENCODE_OTEL_EXPORT_HEADERS;
    } else {
      process.env.MY_OPENCODE_OTEL_EXPORT_HEADERS = previousHeaders;
    }
    globalThis.fetch = originalFetch;
    rmSync(directoryA, { recursive: true, force: true });
    rmSync(directoryB, { recursive: true, force: true });
  }
});

test("gateway event audit bounds the single-flight export queue", () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-event-audit-queue-"));
  const previousConfigPath = process.env.OPENCODE_CONFIG_PATH;
  const originalFetch = globalThis.fetch;
  const configPath = join(directory, "opencode.json");
  writeFileSync(
    configPath,
    JSON.stringify({
      observability: {
        enabled: true,
        provider: "otlp",
        otlp_traces_endpoint: "http://localhost:4318/v1/traces",
      },
    }),
  );
  process.env.OPENCODE_CONFIG_PATH = configPath;
  process.env.MY_OPENCODE_OTEL_EXPORT_ENABLED = "1";
  let requestCount = 0;
  globalThis.fetch = () => {
    requestCount += 1;
    return new Promise(() => undefined);
  };
  try {
    for (let index = 0; index < 300; index += 1) {
      writeGatewayEventAudit(directory, {
        hook: "test",
        reason_code: `queue-${index}`,
      });
    }
    const stats = gatewayEventAuditExportStatsForTest();
    assert.equal(requestCount, 1);
    assert.equal(stats.inFlight, 1);
    assert.equal(stats.queued, 255);
    assert.equal(stats.enqueued, 300);
    assert.equal(stats.dropped, 44);
    resetGatewayEventAuditStateForTest();
    assert.deepEqual(gatewayEventAuditExportStatsForTest(), {
      enqueued: 0,
      sent: 0,
      succeeded: 0,
      failed: 0,
      timedOut: 0,
      httpFailures: 0,
      dropped: 0,
      oversized: 0,
      queued: 0,
      inFlight: 0,
    });
  } finally {
    if (previousConfigPath === undefined) {
      delete process.env.OPENCODE_CONFIG_PATH;
    } else {
      process.env.OPENCODE_CONFIG_PATH = previousConfigPath;
    }
    globalThis.fetch = originalFetch;
    rmSync(directory, { recursive: true, force: true });
  }
});

test("gateway event audit records HTTP failures and cancels response bodies", async () => {
  const directory = mkdtempSync(
    join(tmpdir(), "gateway-event-audit-http-failure-"),
  );
  const previousConfigPath = process.env.OPENCODE_CONFIG_PATH;
  const originalFetch = globalThis.fetch;
  const configPath = join(directory, "opencode.json");
  writeFileSync(
    configPath,
    JSON.stringify({
      observability: {
        enabled: true,
        provider: "otlp",
        otlp_traces_endpoint: "http://localhost:4318/v1/traces",
      },
    }),
  );
  process.env.OPENCODE_CONFIG_PATH = configPath;
  process.env.MY_OPENCODE_OTEL_EXPORT_ENABLED = "1";
  let cancelCount = 0;
  globalThis.fetch = async () => ({
    ok: false,
    status: 500,
    body: {
      async cancel() {
        cancelCount += 1;
      },
    },
  });
  try {
    writeGatewayEventAudit(directory, {
      hook: "test",
      reason_code: "http-failure",
    });
    await flushGatewayEventAuditExportsForTest();
    await new Promise((resolve) => setImmediate(resolve));
    const stats = gatewayEventAuditExportStatsForTest();
    assert.equal(stats.failed, 1);
    assert.equal(stats.httpFailures, 1);
    assert.equal(stats.succeeded, 0);
    assert.equal(cancelCount, 1);
  } finally {
    if (previousConfigPath === undefined) {
      delete process.env.OPENCODE_CONFIG_PATH;
    } else {
      process.env.OPENCODE_CONFIG_PATH = previousConfigPath;
    }
    globalThis.fetch = originalFetch;
    rmSync(directory, { recursive: true, force: true });
  }
});

test("gateway event audit times out an unresolved exporter without retry", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-event-audit-timeout-"));
  const previousConfigPath = process.env.OPENCODE_CONFIG_PATH;
  const previousTimeout = process.env.MY_OPENCODE_OTEL_EXPORT_TIMEOUT_MS;
  const originalFetch = globalThis.fetch;
  const configPath = join(directory, "opencode.json");
  writeFileSync(
    configPath,
    JSON.stringify({
      observability: {
        enabled: true,
        provider: "otlp",
        otlp_traces_endpoint: "http://localhost:4318/v1/traces",
      },
    }),
  );
  process.env.OPENCODE_CONFIG_PATH = configPath;
  process.env.MY_OPENCODE_OTEL_EXPORT_ENABLED = "1";
  process.env.MY_OPENCODE_OTEL_EXPORT_TIMEOUT_MS = "1";
  let requestCount = 0;
  globalThis.fetch = () => {
    requestCount += 1;
    return new Promise(() => undefined);
  };
  try {
    const started = Date.now();
    writeGatewayEventAudit(directory, { hook: "test", reason_code: "timeout" });
    await flushGatewayEventAuditExportsForTest();
    const elapsed = Date.now() - started;
    const stats = gatewayEventAuditExportStatsForTest();
    assert.equal(requestCount, 1);
    assert.equal(stats.timedOut, 1);
    assert.equal(stats.failed, 1);
    assert.equal(stats.sent, 1);
    assert.ok(
      elapsed >= 75 && elapsed < 1000,
      `unexpected timeout duration: ${elapsed}ms`,
    );
  } finally {
    if (previousConfigPath === undefined) {
      delete process.env.OPENCODE_CONFIG_PATH;
    } else {
      process.env.OPENCODE_CONFIG_PATH = previousConfigPath;
    }
    if (previousTimeout === undefined) {
      delete process.env.MY_OPENCODE_OTEL_EXPORT_TIMEOUT_MS;
    } else {
      process.env.MY_OPENCODE_OTEL_EXPORT_TIMEOUT_MS = previousTimeout;
    }
    globalThis.fetch = originalFetch;
    rmSync(directory, { recursive: true, force: true });
  }
});

test("gateway event audit hanging collector does not keep a child process alive", () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-event-audit-child-"));
  const configPath = join(directory, "opencode.json");
  writeFileSync(
    configPath,
    JSON.stringify({
      observability: {
        enabled: true,
        provider: "otlp",
        otlp_traces_endpoint: "http://localhost:4318/v1/traces",
      },
    }),
  );
  const moduleUrl = new URL("../dist/audit/event-audit.js", import.meta.url)
    .href;
  const script = `
    globalThis.fetch = () => new Promise(() => undefined)
    const { writeGatewayEventAudit } = await import(${JSON.stringify(moduleUrl)})
    writeGatewayEventAudit(${JSON.stringify(directory)}, { hook: "test", reason_code: "child-hang" })
  `;
  try {
    const started = Date.now();
    execFileSync(process.execPath, ["--input-type=module", "--eval", script], {
      env: {
        ...process.env,
        MY_OPENCODE_GATEWAY_EVENT_AUDIT: "0",
        MY_OPENCODE_OTEL_EXPORT_ENABLED: "1",
        MY_OPENCODE_OTEL_EXPORT_TIMEOUT_MS: "2000",
        OPENCODE_CONFIG_PATH: configPath,
      },
      stdio: "pipe",
      timeout: 3000,
    });
    assert.ok(Date.now() - started < 2500);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

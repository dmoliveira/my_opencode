import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { gatewayEventAuditPath } from "../dist/audit/event-audit.js";
import { safeCreateHook } from "../dist/hooks/shared/safe-create-hook.js";

test("safe create hook returns null and audits factory failures", () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-safe-hook-"));
  const previousAudit = process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT;
  const previousWrite = process.stderr.write;
  process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = "1";
  process.stderr.write = () => true;
  try {
    const result = safeCreateHook({
      directory,
      hookId: "failing-hook",
      factory: () => {
        throw new Error("boom");
      },
    });
    assert.equal(result, null);
    const audit = readFileSync(gatewayEventAuditPath(directory), "utf8");
    assert.match(audit, /"hook":"failing-hook"/);
    assert.match(audit, /"reason_code":"hook_creation_failed"/);
    assert.match(audit, /"error_message":"boom"/);
  } finally {
    process.stderr.write = previousWrite;
    if (previousAudit === undefined) {
      delete process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT;
    } else {
      process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = previousAudit;
    }
    rmSync(directory, { recursive: true, force: true });
  }
});

test("safe create hook surfaces and throws critical hook failures", () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-safe-hook-"));
  const previousWrite = process.stderr.write;
  let stderr = "";
  process.stderr.write = (chunk, ...rest) => {
    stderr += String(chunk);
    return previousWrite.call(process.stderr, chunk, ...rest);
  };
  try {
    assert.throws(
      () =>
        safeCreateHook({
          directory,
          hookId: "dangerous-command-guard",
          critical: true,
          factory: () => {
            throw new Error("critical boom");
          },
        }),
      /critical boom/,
    );
    assert.match(
      stderr,
      /critical hook dangerous-command-guard failed during init/i,
    );
  } finally {
    process.stderr.write = previousWrite;
    rmSync(directory, { recursive: true, force: true });
  }
});

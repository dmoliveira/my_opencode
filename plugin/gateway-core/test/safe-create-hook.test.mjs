import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

import { gatewayEventAuditPath } from "../dist/audit/event-audit.js";
import { safeCreateHook } from "../dist/hooks/shared/safe-create-hook.js";

const safeCreateHookModuleUrl = pathToFileURL(
  join(import.meta.dirname, "../dist/hooks/shared/safe-create-hook.js"),
).href;

function runSafeCreateHookChild({ directory, critical, audit }) {
  const script = `
    import { safeCreateHook } from ${JSON.stringify(safeCreateHookModuleUrl)};
    let threw = false;
    try {
      const result = safeCreateHook({
        directory: ${JSON.stringify(directory)},
        hookId: ${JSON.stringify(critical ? "dangerous-command-guard" : "failing-hook")},
        critical: ${JSON.stringify(critical)},
        factory: () => { throw new Error(${JSON.stringify(critical ? "critical boom" : "boom")}); },
      });
      if (result !== null) process.exitCode = 3;
    } catch (error) {
      threw = true;
      if (!String(error?.message).includes("critical boom")) process.exitCode = 2;
    }
    if (${JSON.stringify(critical)} && !threw) process.exitCode = 4;
  `;
  return spawnSync(process.execPath, ["--input-type=module", "--eval", script], {
    encoding: "utf8",
    env: {
      ...process.env,
      CI: "true",
      MY_OPENCODE_GATEWAY_EVENT_AUDIT: audit ? "1" : "0",
    },
    timeout: 5_000,
  });
}

test("safe create hook returns null and audits factory failures", () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-safe-hook-"));
  try {
    const result = runSafeCreateHookChild({ directory, critical: false, audit: true });
    assert.equal(result.error, undefined);
    assert.equal(result.status, 0, result.stderr);
    const audit = readFileSync(gatewayEventAuditPath(directory), "utf8");
    assert.match(audit, /"hook":"failing-hook"/);
    assert.match(audit, /"reason_code":"hook_creation_failed"/);
    assert.match(audit, /"error_message":"\[REDACTED\]"/);
    assert.doesNotMatch(audit, /boom/);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

test("safe create hook surfaces and throws critical hook failures", () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-safe-hook-"));
  try {
    const result = runSafeCreateHookChild({ directory, critical: true, audit: false });
    assert.equal(result.error, undefined);
    assert.equal(result.status, 0, result.stderr);
    assert.match(result.stderr, /critical hook dangerous-command-guard failed during init/i);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

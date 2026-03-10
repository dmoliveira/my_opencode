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
  process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = "1";
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
    if (previousAudit === undefined) {
      delete process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT;
    } else {
      process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = previousAudit;
    }
    rmSync(directory, { recursive: true, force: true });
  }
});

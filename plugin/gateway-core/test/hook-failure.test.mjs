import assert from "node:assert/strict";
import test from "node:test";

import { isCriticalGatewayHookId } from "../dist/hooks/shared/hook-failure.js";

test("critical hook registry covers safety and release guards", () => {
  for (const hookId of [
    "agent-denied-tool-enforcer",
    "dangerous-command-guard",
    "dependency-risk-guard",
    "docs-drift-guard",
    "hook-test-parity-guard",
    "noninteractive-shell-guard",
    "pr-body-evidence-guard",
    "safety",
  ]) {
    assert.equal(
      isCriticalGatewayHookId(hookId),
      true,
      `${hookId} should fail closed`,
    );
  }
});

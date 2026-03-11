import assert from "node:assert/strict";
import test from "node:test";

import gatewayCorePlugin from "../dist/index.js";
import { GATEWAY_LLM_DECISION_RUNTIME_BINDINGS } from "../dist/llm-decision-bindings.js";

test("gateway plugin entrypoint exports only the default plugin factory", async () => {
  const entrypoint = await import("../dist/index.js");

  assert.deepEqual(Object.keys(entrypoint), ["default"]);
  assert.equal(entrypoint.default, gatewayCorePlugin);
  assert.equal(typeof gatewayCorePlugin, "function");
});

test("gateway llm decision runtime bindings stay aligned to hook ids", () => {
  assert.deepEqual(GATEWAY_LLM_DECISION_RUNTIME_BINDINGS, {
    agentDeniedToolEnforcer: "agent-denied-tool-enforcer",
    agentModelResolver: "agent-model-resolver",
    delegationFallbackOrchestrator: "delegation-fallback-orchestrator",
    validationEvidenceLedger: "validation-evidence-ledger",
    mistakeLedger: "mistake-ledger",
    autoSlashCommand: "auto-slash-command",
    taskResumeInfo: "task-resume-info",
    providerErrorClassifier: "provider-error-classifier",
    todoContinuationEnforcer: "todo-continuation-enforcer",
    doneProofEnforcer: "done-proof-enforcer",
    prBodyEvidenceGuard: "pr-body-evidence-guard",
  });
});

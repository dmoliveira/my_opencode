import assert from "node:assert/strict";
import test from "node:test";

import { GATEWAY_LLM_DECISION_RUNTIME_BINDINGS } from "../dist/index.js";

test("gateway llm decision runtime bindings stay aligned to hook ids", () => {
  assert.deepEqual(GATEWAY_LLM_DECISION_RUNTIME_BINDINGS, {
    agentDeniedToolEnforcer: "agent-denied-tool-enforcer",
    agentModelResolver: "agent-model-resolver",
    delegationFallbackOrchestrator: "delegation-fallback-orchestrator",
    validationEvidenceLedger: "validation-evidence-ledger",
    autoSlashCommand: "auto-slash-command",
    providerErrorClassifier: "provider-error-classifier",
    doneProofEnforcer: "done-proof-enforcer",
    prBodyEvidenceGuard: "pr-body-evidence-guard",
  });
});

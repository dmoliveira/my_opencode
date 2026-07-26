export const GATEWAY_LLM_DECISION_MODES = [
  "disabled",
  "shadow",
  "assist",
  "enforce",
] as const;

export type GatewayLlmDecisionMode =
  (typeof GATEWAY_LLM_DECISION_MODES)[number];

export const GATEWAY_LLM_DECISION_RUNTIME_BINDINGS = {
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
} as const;

export const GATEWAY_LLM_DECISION_HOOK_IDS: readonly string[] = Object.freeze(
  Object.values(GATEWAY_LLM_DECISION_RUNTIME_BINDINGS),
);

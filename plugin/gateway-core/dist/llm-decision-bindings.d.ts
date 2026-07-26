export declare const GATEWAY_LLM_DECISION_MODES: readonly ["disabled", "shadow", "assist", "enforce"];
export type GatewayLlmDecisionMode = (typeof GATEWAY_LLM_DECISION_MODES)[number];
export declare const GATEWAY_LLM_DECISION_RUNTIME_BINDINGS: {
    readonly agentDeniedToolEnforcer: "agent-denied-tool-enforcer";
    readonly agentModelResolver: "agent-model-resolver";
    readonly delegationFallbackOrchestrator: "delegation-fallback-orchestrator";
    readonly validationEvidenceLedger: "validation-evidence-ledger";
    readonly mistakeLedger: "mistake-ledger";
    readonly autoSlashCommand: "auto-slash-command";
    readonly taskResumeInfo: "task-resume-info";
    readonly providerErrorClassifier: "provider-error-classifier";
    readonly todoContinuationEnforcer: "todo-continuation-enforcer";
    readonly doneProofEnforcer: "done-proof-enforcer";
    readonly prBodyEvidenceGuard: "pr-body-evidence-guard";
};
export declare const GATEWAY_LLM_DECISION_HOOK_IDS: readonly string[];

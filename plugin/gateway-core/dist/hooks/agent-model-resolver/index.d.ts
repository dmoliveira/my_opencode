import type { GatewayHook } from "../registry.js";
import { type LlmDecisionRuntime } from "../shared/llm-decision-runtime.js";
interface AgentRuntimePolicy {
    overrideDelta?: number;
    intentThreshold?: number;
}
export declare function createAgentModelResolverHook(options: {
    directory: string;
    enabled: boolean;
    defaultOverrideDelta: number;
    defaultIntentThreshold: number;
    agentPolicyOverrides: Record<string, AgentRuntimePolicy>;
    decisionRuntime?: LlmDecisionRuntime;
}): GatewayHook;
export {};

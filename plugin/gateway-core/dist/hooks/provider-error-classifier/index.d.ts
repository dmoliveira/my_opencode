import type { GatewayHook } from "../registry.js";
import type { LlmDecisionRuntime } from "../shared/llm-decision-runtime.js";
interface GatewayClient {
    session?: {
        promptAsync(args: {
            path: {
                id: string;
            };
            body: {
                parts: Array<{
                    type: string;
                    text: string;
                }>;
            };
            query?: {
                directory?: string;
            };
        }): Promise<void>;
    };
}
export declare function createProviderErrorClassifierHook(options: {
    directory: string;
    enabled: boolean;
    client?: GatewayClient;
    cooldownMs: number;
    decisionRuntime?: LlmDecisionRuntime;
}): GatewayHook;
export {};

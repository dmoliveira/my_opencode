import type { GatewayHook } from "../registry.js";
import type { LlmDecisionRuntime } from "../shared/llm-decision-runtime.js";
import type { StopContinuationGuard } from "../stop-continuation-guard/index.js";
interface GatewayClient {
    session?: {
        messages(args: {
            path: {
                id: string;
            };
            query?: {
                directory?: string;
            };
        }): Promise<{
            data?: Array<{
                info?: {
                    role?: string;
                    error?: unknown;
                    time?: {
                        completed?: number;
                    };
                };
                parts?: Array<{
                    type: string;
                    text?: string;
                    synthetic?: boolean;
                }>;
            }>;
        }>;
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
export declare function createTodoContinuationEnforcerHook(options: {
    directory: string;
    enabled: boolean;
    client?: GatewayClient;
    stopGuard?: StopContinuationGuard;
    decisionRuntime?: LlmDecisionRuntime;
    cooldownMs: number;
    maxConsecutiveFailures: number;
}): GatewayHook;
export {};

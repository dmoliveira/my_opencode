import type { GatewayHook } from "../registry.js";
export declare function createSubagentQuestionBlockerHook(options: {
    directory: string;
    enabled: boolean;
    sessionPatterns: string[];
}): GatewayHook;

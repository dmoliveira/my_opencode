import type { GatewayHook } from "../registry.js";
export declare function createAgentContextShaperHook(options: {
    directory: string;
    enabled: boolean;
}): GatewayHook;

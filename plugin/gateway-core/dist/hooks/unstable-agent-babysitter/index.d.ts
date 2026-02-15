import type { GatewayHook } from "../registry.js";
export declare function createUnstableAgentBabysitterHook(options: {
    enabled: boolean;
    riskyPatterns: string[];
}): GatewayHook;

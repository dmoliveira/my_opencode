import type { GatewayHook } from "../registry.js";
export declare function createDocsDriftGuardHook(options: {
    directory: string;
    enabled: boolean;
    sourcePatterns: string[];
    docsPatterns: string[];
    blockOnDrift: boolean;
}): GatewayHook;

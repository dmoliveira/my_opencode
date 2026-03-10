import type { GatewayHook } from "../registry.js";
export declare function createMistakeLedgerHook(options: {
    directory: string;
    enabled: boolean;
    path: string;
}): GatewayHook;

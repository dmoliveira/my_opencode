import type { GatewayHook } from "../registry.js";
export declare function createDirectWorkWarningHook(options: {
    directory: string;
    enabled: boolean;
    blockRepeatedEdits: boolean;
}): GatewayHook;

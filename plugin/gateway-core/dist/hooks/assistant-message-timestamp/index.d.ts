import type { GatewayHook } from "../registry.js";
export declare function formatAssistantMessageTimestamp(timestamp: number): string;
export declare function createAssistantMessageTimestampHook(options: {
    enabled: boolean;
    now?: () => number;
}): GatewayHook;

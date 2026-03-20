import type { GatewayHook } from "../registry.js";
export declare function createLongTurnWatchdogHook(options: {
    directory: string;
    client?: unknown;
    enabled: boolean;
    warningThresholdMs: number;
    toolCallWarningThreshold: number;
    reminderCooldownMs: number;
    maxSessionStateEntries: number;
    prefix: string;
    now?: () => number;
}): GatewayHook;

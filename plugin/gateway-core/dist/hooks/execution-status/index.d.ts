import type { GatewayHook } from "../registry.js";
export declare function createExecutionStatusHook(options: {
    directory: string;
    enabled: boolean;
    maxSessions: number;
    maxLabelChars: number;
}): GatewayHook;

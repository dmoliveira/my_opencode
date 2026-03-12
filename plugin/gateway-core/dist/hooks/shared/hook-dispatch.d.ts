import type { GatewayHook } from "../registry.js";
export interface HookDispatchResult {
    ok: boolean;
    critical: boolean;
    blocked: boolean;
    error?: Error;
}
export declare function dispatchGatewayHookEvent(input: {
    hook: GatewayHook;
    eventType: string;
    payload: unknown;
    directory: string;
}): Promise<HookDispatchResult>;

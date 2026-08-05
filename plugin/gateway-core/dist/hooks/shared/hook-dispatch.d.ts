import type { GatewayHook } from "../registry.js";
import type { HookDispatchLatencyRecorder } from "./hook-dispatch-latency.js";
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
    latency?: HookDispatchLatencyRecorder;
}): Promise<HookDispatchResult>;

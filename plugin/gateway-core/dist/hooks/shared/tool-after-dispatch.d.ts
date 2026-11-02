import type { GatewayHook } from "../registry.js";
import { dispatchGatewayHookEvent } from "./hook-dispatch.js";
interface ToolAfterPayload {
    input: {
        tool: string;
        sessionID?: string;
        callID?: string;
        args?: {
            command?: string;
        };
    };
    output: {
        output?: unknown;
        metadata?: unknown;
    };
    directory: string;
}
export declare function dispatchToolAfterHooks(selectedHooks: GatewayHook[], payload: ToolAfterPayload, dispatch?: typeof dispatchGatewayHookEvent): Promise<void>;
export {};

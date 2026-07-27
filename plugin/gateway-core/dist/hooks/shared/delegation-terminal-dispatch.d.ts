import type { GatewayHook } from "../registry.js";
import type { HookDispatchResult } from "./hook-dispatch.js";
export declare const DELEGATION_HOOK_EVENTS: readonly ["session.created", "session.updated", "session.idle", "message.updated", "session.deleted", "tool.execute.before", "tool.execute.before.error", "tool.execute.after"];
export declare function dispatchDelegationTerminalHooks(input: {
    hooks: GatewayHook[];
    dispatch: (hook: GatewayHook) => Promise<HookDispatchResult>;
    cleanup: () => void;
}): Promise<void>;

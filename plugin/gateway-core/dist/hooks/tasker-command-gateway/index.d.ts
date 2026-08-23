import type { GatewayHook } from "../registry.js";
import { type TaskerSandbox } from "./command-policy.js";
type AgentResolver = (sessionID: string) => string | undefined | Promise<string | undefined>;
type SandboxResolver = (sessionID: string) => TaskerSandbox | undefined | Promise<TaskerSandbox | undefined>;
export declare function createTaskerCommandGatewayHook(options: {
    directory: string;
    resolveAgent: AgentResolver;
    resolveSandbox?: SandboxResolver;
    knownRecordTargets?: ReadonlyMap<string, TaskerSandbox>;
    failClosedOnUnknownIdentity?: boolean;
}): GatewayHook;
export {};

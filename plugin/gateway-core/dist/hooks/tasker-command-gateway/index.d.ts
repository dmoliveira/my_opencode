import type { GatewayHook } from "../registry.js";
import { type TaskerSandbox } from "./command-policy.js";
type AgentResolver = (sessionID: string) => string | undefined | Promise<string | undefined>;
type SandboxResolver = (sessionID: string) => TaskerSandbox | undefined | Promise<TaskerSandbox | undefined>;
type ParentResolver = (sessionID: string) => Promise<string | null | undefined>;
export declare function createTaskerCommandGatewayHook(options: {
    directory: string;
    resolveAgent: AgentResolver;
    resolveSandbox?: SandboxResolver;
    resolveParent?: ParentResolver;
    wasTasker?: (sessionID: string) => Promise<boolean | undefined>;
    initialResearchPrompt?: (sessionID: string) => Promise<string | undefined>;
    knownRecordTargets?: ReadonlyMap<string, TaskerSandbox>;
    failClosedOnUnknownIdentity?: boolean;
}): GatewayHook;
export {};

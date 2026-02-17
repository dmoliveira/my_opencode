import type { GatewayHook } from "../registry.js";
import type { ContextCollector } from "../context-injector/collector.js";
interface AutopilotLoopDefaults {
    enabled: boolean;
    maxIterations: number;
    completionMode: "promise" | "objective";
    completionPromise: string;
}
export declare function createAutopilotLoopHook(options: {
    directory: string;
    defaults: AutopilotLoopDefaults;
    collector?: ContextCollector;
}): GatewayHook;
export {};

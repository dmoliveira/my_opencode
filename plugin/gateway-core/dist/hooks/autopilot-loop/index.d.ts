import type { GatewayHook } from "../registry.js";
interface AutopilotLoopDefaults {
    enabled: boolean;
    maxIterations: number;
    completionMode: "promise" | "objective";
    completionPromise: string;
}
export declare function createAutopilotLoopHook(options: {
    directory: string;
    defaults: AutopilotLoopDefaults;
}): GatewayHook;
export {};

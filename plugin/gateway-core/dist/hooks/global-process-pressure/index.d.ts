import type { GatewayHook } from "../registry.js";
interface PressureSample {
    opencodeProcessCount: number;
    continueProcessCount: number;
    maxRssMb: number;
}
export declare function createGlobalProcessPressureHook(options: {
    directory: string;
    enabled: boolean;
    checkCooldownToolCalls: number;
    reminderCooldownToolCalls: number;
    warningContinueSessions: number;
    warningOpencodeProcesses: number;
    warningMaxRssMb: number;
    guardMarkerMode: "nerd" | "plain" | "both";
    guardVerbosity: "minimal" | "normal" | "debug";
    maxSessionStateEntries: number;
    sampler?: () => PressureSample;
}): GatewayHook;
export {};

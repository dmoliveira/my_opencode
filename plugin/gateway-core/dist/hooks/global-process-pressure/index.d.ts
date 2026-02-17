import type { GatewayHook } from "../registry.js";
import type { StopContinuationGuard } from "../stop-continuation-guard/index.js";
interface PressureSample {
    opencodeProcessCount: number;
    continueProcessCount: number;
    maxRssMb: number;
}
export declare function createGlobalProcessPressureHook(options: {
    directory: string;
    stopGuard?: StopContinuationGuard;
    enabled: boolean;
    checkCooldownToolCalls: number;
    reminderCooldownToolCalls: number;
    criticalReminderCooldownToolCalls: number;
    warningContinueSessions: number;
    warningOpencodeProcesses: number;
    warningMaxRssMb: number;
    criticalMaxRssMb: number;
    autoPauseOnCritical: boolean;
    guardMarkerMode: "nerd" | "plain" | "both";
    guardVerbosity: "minimal" | "normal" | "debug";
    maxSessionStateEntries: number;
    sampler?: () => PressureSample;
}): GatewayHook;
export {};

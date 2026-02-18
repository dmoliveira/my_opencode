import type { GatewayHook } from "../registry.js";
import type { StopContinuationGuard } from "../stop-continuation-guard/index.js";
interface SelfSessionPressureSample {
    pid: number;
    cpuPct: number;
    memPct: number;
    rssMb: number;
    elapsed: string;
    elapsedSeconds: number;
    cwd: string;
}
interface PressureSample {
    opencodeProcessCount: number;
    continueProcessCount: number;
    maxRssMb: number;
    selfSession: SelfSessionPressureSample | null;
}
export declare function createGlobalProcessPressureHook(options: {
    directory: string;
    stopGuard?: StopContinuationGuard;
    enabled: boolean;
    checkCooldownToolCalls: number;
    reminderCooldownToolCalls: number;
    criticalReminderCooldownToolCalls: number;
    criticalEscalationWindowToolCalls: number;
    criticalPauseAfterEvents: number;
    criticalEscalationAfterEvents: number;
    warningContinueSessions: number;
    warningOpencodeProcesses: number;
    warningMaxRssMb: number;
    criticalMaxRssMb: number;
    autoPauseOnCritical: boolean;
    notifyOnCritical: boolean;
    guardMarkerMode: "nerd" | "plain" | "both";
    guardVerbosity: "minimal" | "normal" | "debug";
    maxSessionStateEntries: number;
    selfSeverityOperator?: "any" | "all";
    selfHighCpuPct?: number;
    selfHighRssMb?: number;
    selfHighElapsed?: string;
    selfHighLabel?: string;
    selfLowLabel?: string;
    selfAppendMarker?: boolean;
    sampler?: () => PressureSample;
}): GatewayHook;
export {};

import type { GatewayHook } from "../registry.js";
export declare function createAdaptiveValidationSchedulerHook(options: {
    directory: string;
    enabled: boolean;
    reminderEditThreshold: number;
}): GatewayHook;

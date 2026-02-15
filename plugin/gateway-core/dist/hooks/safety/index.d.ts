import type { GatewayHook } from "../registry.js";
export declare function createSafetyHook(options: {
    directory: string;
    orphanMaxAgeHours: number;
}): GatewayHook;

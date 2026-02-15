import type { GatewayHook } from "../registry.js";
export declare function createAgentReservationGuardHook(options: {
    directory: string;
    enabled: boolean;
    enforce: boolean;
    reservationEnvKeys: string[];
}): GatewayHook;

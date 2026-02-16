import type { GatewayHook } from "../registry.js";
export declare function createParallelWriterConflictGuardHook(options: {
    directory: string;
    enabled: boolean;
    maxConcurrentWriters: number;
    writerCountEnvKeys: string[];
    reservationPathsEnvKeys: string[];
    activeReservationPathsEnvKeys: string[];
    enforceReservationCoverage: boolean;
}): GatewayHook;

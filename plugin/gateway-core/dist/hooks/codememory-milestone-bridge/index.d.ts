import { spawn } from "node:child_process";
import type { GatewayHook } from "../registry.js";
type SpawnProcess = typeof spawn;
export declare function createCodememoryMilestoneBridgeHook(options: {
    directory: string;
    enabled: boolean;
    command: string;
    timeoutMs: number;
    maxQueueEntries: number;
    spawnProcess?: SpawnProcess;
}): GatewayHook;
export {};

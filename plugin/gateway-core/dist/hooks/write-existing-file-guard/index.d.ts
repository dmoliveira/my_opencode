import type { GatewayHook } from "../registry.js";
export declare function createWriteExistingFileGuardHook(options: {
    directory: string;
    enabled: boolean;
}): GatewayHook;

import type { GatewayHook } from "../registry.js";
export declare function createAutoSlashCommandHook(options: {
    directory: string;
    enabled: boolean;
}): GatewayHook;

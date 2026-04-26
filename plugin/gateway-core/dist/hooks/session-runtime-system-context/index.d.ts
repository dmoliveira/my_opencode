import type { GatewayHook } from "../registry.js";
export declare function createSessionRuntimeSystemContextHook(options: {
    directory: string;
    enabled: boolean;
    conciseModeEnabled: boolean;
    conciseDefaultMode: "off" | "lite" | "full" | "ultra";
}): GatewayHook;

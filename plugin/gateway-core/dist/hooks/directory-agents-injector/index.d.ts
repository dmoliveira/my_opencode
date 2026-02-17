import type { GatewayHook } from "../registry.js";
export declare function createDirectoryAgentsInjectorHook(options: {
    directory: string;
    enabled: boolean;
    maxChars: number;
}): GatewayHook;

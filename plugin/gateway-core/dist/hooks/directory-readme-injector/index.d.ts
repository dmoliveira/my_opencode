import type { GatewayHook } from "../registry.js";
export declare function createDirectoryReadmeInjectorHook(options: {
    directory: string;
    enabled: boolean;
    maxChars: number;
}): GatewayHook;

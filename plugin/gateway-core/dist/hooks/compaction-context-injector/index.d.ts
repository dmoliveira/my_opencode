import type { GatewayHook } from "../registry.js";
export declare function createCompactionContextInjectorHook(options: {
    directory: string;
    enabled: boolean;
}): GatewayHook;

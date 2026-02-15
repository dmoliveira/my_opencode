import type { GatewayHook } from "../registry.js";
export declare function createRulesInjectorHook(options: {
    directory: string;
    enabled: boolean;
}): GatewayHook;

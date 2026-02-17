import type { GatewayHook } from "../registry.js";
import type { ContextCollector } from "./collector.js";
export declare function createContextInjectorHook(options: {
    directory: string;
    enabled: boolean;
    collector: ContextCollector;
}): GatewayHook;

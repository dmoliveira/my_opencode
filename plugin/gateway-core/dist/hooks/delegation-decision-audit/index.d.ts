import type { GatewayHook } from "../registry.js";
export declare function createDelegationDecisionAuditHook(options: {
    directory: string;
    enabled: boolean;
}): GatewayHook;

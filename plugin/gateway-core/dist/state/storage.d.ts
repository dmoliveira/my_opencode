import type { GatewayState } from "./types.js";
export declare const DEFAULT_STATE_PATH = ".opencode/gateway-core.state.json";
export declare function resolveGatewayStatePath(directory: string, relativePath?: string): string;
export declare function loadGatewayState(directory: string, relativePath?: string): GatewayState | null;
export declare function saveGatewayState(directory: string, state: GatewayState, relativePath?: string): void;
export declare function nowIso(): string;
export declare function deactivateGatewayLoop(directory: string, reason: string, relativePath?: string): GatewayState | null;
export declare function cleanupOrphanGatewayLoop(directory: string, maxAgeHours: number, relativePath?: string): {
    changed: boolean;
    reason: string;
    state: GatewayState | null;
};

import type { GatewayState } from "./types.js";
export declare const DEFAULT_STATE_PATH = ".opencode/gateway-core.state.json";
export declare function resolveGatewayStatePath(directory: string, relativePath?: string): string;
export declare function loadGatewayState(directory: string, relativePath?: string): GatewayState | null;
export declare function saveGatewayState(directory: string, state: GatewayState, relativePath?: string): void;

import { type GatewayConfig } from "./schema.js";
export interface GatewayConfigLayerMeta {
    kind: "env" | "home" | "project" | "bundled";
    path: string;
    exists: boolean;
    loaded: boolean;
    error?: string;
}
export interface GatewayConfigSourceMeta {
    sidecarPath: string;
    sidecarExists: boolean;
    sidecarLoaded: boolean;
    sidecarError?: string;
    layers: GatewayConfigLayerMeta[];
}
export declare function loadGatewayConfigSourceWithMeta(directory: string, source: unknown, override?: unknown): {
    source: Record<string, unknown>;
    meta: GatewayConfigSourceMeta;
};
export declare function loadGatewayConfigSource(directory: string, source: unknown): Record<string, unknown>;
export declare function loadGatewayConfig(raw: unknown): GatewayConfig;

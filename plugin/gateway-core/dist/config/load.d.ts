import { type GatewayConfig } from "./schema.js";
export interface GatewayConfigSourceMeta {
    sidecarPath: string;
    sidecarExists: boolean;
    sidecarLoaded: boolean;
    sidecarError?: string;
}
export declare function loadGatewayConfigSourceWithMeta(directory: string, source: unknown): {
    source: Record<string, unknown>;
    meta: GatewayConfigSourceMeta;
};
export declare function loadGatewayConfigSource(directory: string, source: unknown): Record<string, unknown>;
export declare function loadGatewayConfig(raw: unknown): GatewayConfig;

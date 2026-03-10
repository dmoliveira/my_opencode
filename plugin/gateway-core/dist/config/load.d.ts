import { type GatewayConfig } from "./schema.js";
export declare function loadGatewayConfigSource(directory: string, source: unknown): Record<string, unknown>;
export declare function loadGatewayConfig(raw: unknown): GatewayConfig;

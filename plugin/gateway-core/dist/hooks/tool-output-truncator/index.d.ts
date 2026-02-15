import type { GatewayHook } from "../registry.js";
export declare function createToolOutputTruncatorHook(options: {
    directory: string;
    enabled: boolean;
    maxChars: number;
    maxLines: number;
    tools: string[];
}): GatewayHook;

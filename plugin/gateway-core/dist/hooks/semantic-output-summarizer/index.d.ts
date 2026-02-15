import type { GatewayHook } from "../registry.js";
export declare function createSemanticOutputSummarizerHook(options: {
    directory: string;
    enabled: boolean;
    minChars: number;
    minLines: number;
    maxSummaryLines: number;
}): GatewayHook;

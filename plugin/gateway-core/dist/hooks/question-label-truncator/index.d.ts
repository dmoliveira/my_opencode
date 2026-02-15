import type { GatewayHook } from "../registry.js";
export declare function createQuestionLabelTruncatorHook(options: {
    enabled: boolean;
    maxLength: number;
}): GatewayHook;

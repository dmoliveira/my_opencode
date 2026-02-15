import type { GatewayHook } from "../registry.js";
export declare function createReadBudgetOptimizerHook(options: {
    directory: string;
    enabled: boolean;
    smallReadLimit: number;
    maxConsecutiveSmallReads: number;
}): GatewayHook;

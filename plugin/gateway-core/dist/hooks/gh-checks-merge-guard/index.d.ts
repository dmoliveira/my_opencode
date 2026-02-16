import type { GatewayHook } from "../registry.js";
interface PrViewPayload {
    isDraft?: unknown;
    reviewDecision?: unknown;
    mergeStateStatus?: unknown;
    statusCheckRollup?: unknown;
}
interface InspectPrInput {
    directory: string;
    selector: string;
}
export declare function createGhChecksMergeGuardHook(options: {
    directory: string;
    enabled: boolean;
    blockDraft: boolean;
    requireApprovedReview: boolean;
    requirePassingChecks: boolean;
    blockedMergeStates: string[];
    failOpenOnError: boolean;
    inspectPr?: (input: InspectPrInput) => PrViewPayload;
}): GatewayHook;
export {};

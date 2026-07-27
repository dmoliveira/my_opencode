export declare const STATE_RELATIVE_PATH = ".opencode/gateway-core.state.json";
export declare const STATE_DIRECTORY_NAME = ".opencode";
export declare const STATE_FILE_NAME = "gateway-core.state.json";
export declare const LOCK_DIRECTORY_NAME = "gateway-core.state.json.lock";
export declare const OWNER_TOKEN_NAME = "owner-token";
export declare const STAGE_PREFIX = ".gateway-core.state.json.stage-";
export declare const LOCK_TIMEOUT_MS = 2000;
export declare const LOCK_POLL_MS = 20;
export declare const MAX_STATE_BYTES: number;
export declare const PRIVATE_DIRECTORY_MODE = 448;
export declare const PRIVATE_FILE_MODE = 384;
export declare const TOKEN_RANDOM_BYTES = 32;
export declare const TOKEN_TEXT_BYTES = 65;
export declare const JSON_INDENT = 2;
export declare const MAX_SAFE_INTEGER = 9007199254740991;
export declare const LOCK_RECOVERY_GUIDANCE = "stop the gateway state owner, then manually remove the lock directory";
declare const DOMAIN_KEYS: {
    readonly activeLoop: Set<string>;
    readonly conciseMode: Set<string>;
};
export type GatewayStateDomain = keyof typeof DOMAIN_KEYS;
export type GatewayStateMutationMode = "replace" | "patch";
export type JsonRecord = Record<string, unknown>;
export interface GatewayStateDomainMutation {
    value: unknown;
    mode?: GatewayStateMutationMode;
    rootUpdates?: Record<string, unknown>;
}
export interface GatewayStateCommitResult {
    path: string;
    committed: boolean;
    durability: "not_committed" | "synced" | "uncertain";
    lockReleased: boolean;
}
export interface GatewayStateTransactionResult {
    state: JsonRecord;
    changed: boolean;
    commit: GatewayStateCommitResult | null;
}
export interface GatewayStateTransactionOptions {
    timeoutMs?: number;
    failureInjector?: (phase: string) => void;
}
export interface GatewayStateReadOptions {
    failureInjector?: (phase: string) => void;
}
export declare class GatewayStateProtocolError extends Error {
    reasonCode: string;
    phase: string;
    committed: boolean;
    durability: "not_committed" | "synced" | "uncertain";
    lockReleased: boolean;
    causeCode: string | null;
    secondaryReasonCode: string | null;
    constructor(reasonCode: string, message: string, options: {
        phase: string;
        committed?: boolean;
        durability?: "not_committed" | "synced" | "uncertain";
        lockReleased?: boolean;
        cause?: unknown;
        secondaryReasonCode?: string | null;
    });
    toJSON(): Record<string, unknown>;
}
export declare function resolveStatePath(directory: string): string;
export declare function resolveLockPath(directory: string): string;
export declare function loadRawGatewayState(directory: string, options?: GatewayStateReadOptions): JsonRecord;
export declare function loadRawGatewayStateSnapshot(directory: string, options?: GatewayStateReadOptions): {
    state: JsonRecord;
    exists: boolean;
};
export declare function transactGatewayStateDomain(directory: string, domain: GatewayStateDomain, mutator: (current: unknown, state: JsonRecord) => GatewayStateDomainMutation | null, options?: GatewayStateTransactionOptions): GatewayStateTransactionResult;
export declare function updateGatewayStateDomain(directory: string, domain: GatewayStateDomain, value: unknown, mutationOptions?: {
    mode?: GatewayStateMutationMode;
    rootUpdates?: Record<string, unknown>;
}, transactionOptions?: GatewayStateTransactionOptions): GatewayStateTransactionResult;
export declare function gatewayStateLockStatus(directory: string): Record<string, unknown>;
export {};

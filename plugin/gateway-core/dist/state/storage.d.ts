import type { GatewayState } from "./types.js";
import { GatewayStateProtocolError, LOCK_DIRECTORY_NAME, LOCK_POLL_MS, LOCK_RECOVERY_GUIDANCE, LOCK_TIMEOUT_MS, MAX_STATE_BYTES, OWNER_TOKEN_NAME, PRIVATE_DIRECTORY_MODE, PRIVATE_FILE_MODE, STAGE_PREFIX, STATE_DIRECTORY_NAME, STATE_FILE_NAME, gatewayStateLockStatus, loadRawGatewayState, resolveLockPath, transactGatewayStateDomain, updateGatewayStateDomain, type GatewayStateCommitResult, type GatewayStateDomainMutation } from "./protocol.js";
export { GatewayStateProtocolError, LOCK_DIRECTORY_NAME, LOCK_POLL_MS, LOCK_RECOVERY_GUIDANCE, LOCK_TIMEOUT_MS, MAX_STATE_BYTES, OWNER_TOKEN_NAME, PRIVATE_DIRECTORY_MODE, PRIVATE_FILE_MODE, STAGE_PREFIX, STATE_DIRECTORY_NAME, STATE_FILE_NAME, gatewayStateLockStatus, loadRawGatewayState, resolveLockPath, transactGatewayStateDomain, updateGatewayStateDomain, };
export declare const DEFAULT_STATE_PATH = ".opencode/gateway-core.state.json";
export declare function resolveGatewayStatePath(directory: string, relativePath?: string): string;
export declare function loadGatewayState(directory: string, relativePath?: string): GatewayState | null;
export declare function saveGatewayState(directory: string, state: GatewayState, relativePath?: string): GatewayStateCommitResult;
export declare function saveGatewayConciseMode(directory: string, conciseMode: GatewayState["conciseMode"], metadata: {
    lastUpdatedAt: string;
    source?: string;
}): GatewayStateCommitResult;
export declare function nowIso(): string;
export declare function deactivateGatewayLoop(directory: string, reason: string, relativePath?: string): GatewayState | null;
export declare function cleanupOrphanGatewayLoop(directory: string, maxAgeHours: number, relativePath?: string): {
    changed: boolean;
    reason: string;
    state: GatewayState | null;
};
export type { GatewayStateCommitResult, GatewayStateDomainMutation };

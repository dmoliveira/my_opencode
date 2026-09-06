import type { GatewayHook } from "../registry.js";
import { type SecretRedactionWorkerFactory, type SecretRedactionLimits } from "../shared/secret-redaction.js";
export declare function createSecretLeakGuardHook(options: {
    directory: string;
    enabled: boolean;
    redactionToken: string;
    patterns: string[];
    limits: SecretRedactionLimits;
    isolateCustomPatterns?: boolean;
    workerFactory?: SecretRedactionWorkerFactory;
    workerTimeoutMs?: number;
}): GatewayHook;

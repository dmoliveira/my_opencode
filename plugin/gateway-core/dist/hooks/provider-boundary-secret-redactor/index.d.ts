import { type ProviderSecretRedactionLimits, type SecretRedactionLimits, type SecretRedactionWorkerFactory } from "../shared/secret-redaction.js";
export interface ProviderBoundarySecretFinalizer {
    finalizeMessages(payload: {
        input?: {
            sessionID?: string;
        };
        output?: {
            messages?: unknown;
        };
        directory?: string;
    }): Promise<void>;
    finalizeSystem(payload: {
        input?: {
            sessionID?: string;
        };
        output?: {
            system?: unknown;
        };
        directory?: string;
    }): Promise<void>;
}
export declare function createProviderBoundarySecretFinalizer(options: {
    directory: string;
    patterns: string[];
    redactionToken: string;
    limits: SecretRedactionLimits;
    providerLimits: ProviderSecretRedactionLimits;
    omittableOpaqueAttachmentPatternIndex?: number | null;
    isolateCustomPatterns?: boolean;
    workerFactory?: SecretRedactionWorkerFactory;
    workerTimeoutMs?: number;
}): ProviderBoundarySecretFinalizer;

import { type SecretRedactionLimits } from "../shared/secret-redaction.js";
export interface ProviderBoundarySecretFinalizer {
    finalizeMessages(payload: {
        input?: {
            sessionID?: string;
        };
        output?: {
            messages?: unknown;
        };
        directory?: string;
    }): void;
    finalizeSystem(payload: {
        input?: {
            sessionID?: string;
        };
        output?: {
            system?: unknown;
        };
        directory?: string;
    }): void;
}
export declare function createProviderBoundarySecretFinalizer(options: {
    directory: string;
    patterns: string[];
    redactionToken: string;
    limits: SecretRedactionLimits;
}): ProviderBoundarySecretFinalizer;

import type { GatewayHook } from "../registry.js";
interface EnvelopeContent {
    mode: "metadata" | "redacted_preview";
    char_count: number;
    sha256: string;
    preview?: string;
    truncated?: boolean;
    redacted_fields?: number;
    omitted_reason?: "redaction_failed";
}
export interface IntentIngressEnvelope {
    version: 1;
    envelope_id: string;
    project_digest: string;
    observed_at: string;
    source: {
        kind: "user";
        session_id: string;
        message_id: string;
    };
    content: EnvelopeContent;
}
type PersistResult = {
    outcome: "enqueued";
    durability: "synced" | "file_synced";
} | {
    outcome: "deduplicated";
} | {
    outcome: "overflow";
} | {
    outcome: "conflict";
};
interface PersistOptions {
    stateDir: string;
    maxEnvelopeBytes: number;
    softMaxPendingEntries: number;
    failureInjector?: (phase: string) => void;
}
interface HookOptions {
    directory: string;
    enabled: boolean;
    captureContent: boolean;
    stateDir: string;
    maxInputChars: number;
    maxContentChars: number;
    maxEnvelopeBytes: number;
    softMaxPendingEntries: number;
    redactionToken: string;
    secretPatterns: string[];
    secretLimits: {
        maxDepth: number;
        maxNodes: number;
    };
}
export declare function persistIntentIngressEnvelope(envelope: IntentIngressEnvelope, options: PersistOptions): Promise<PersistResult>;
export declare function compareIntentIngressEnvelopes(left: IntentIngressEnvelope, right: IntentIngressEnvelope): number;
export declare function createIntentIngressOutboxHook(options: HookOptions): GatewayHook;
export {};

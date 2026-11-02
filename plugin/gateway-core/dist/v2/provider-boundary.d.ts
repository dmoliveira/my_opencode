import type { SecretRedactor } from "../hooks/shared/secret-redaction.js";
type RequestKind = "context" | "compaction" | "generate" | "title";
interface RequestEvent {
    system: unknown;
    messages: unknown;
}
interface Registration {
    dispose(): Promise<void>;
}
interface SessionHooks {
    hook(kind: RequestKind, callback: (event: RequestEvent) => Promise<void>): Promise<Registration>;
}
/**
 * Registers the model-context portion of the V2 redaction port. This is not a
 * complete provider boundary: later plugins and raw HTTP/WebSocket hooks can
 * still modify requests. Do not enable this as a standalone security plugin.
 */
export declare function registerV2ContextRedaction(session: SessionHooks, redactor: Pick<SecretRedactor, "redactMutableValueAsync">): Promise<() => Promise<void>>;
export {};

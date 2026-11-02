import type { SecretRedactor } from "../hooks/shared/secret-redaction.js";
import type { SessionHooks } from "./types.js";
/**
 * Registers the model-context portion of the V2 redaction port. This is not a
 * complete provider boundary: later plugins and raw HTTP/WebSocket hooks can
 * still modify requests. Do not enable this as a standalone security plugin.
 */
export declare function registerV2ContextRedaction(session: SessionHooks, redactor: Pick<SecretRedactor, "redactMutableValueAsync">): Promise<() => Promise<void>>;
/** Experimental final transport scan. It is not a production-ready boundary:
 * later plugin hooks and provider paths not covered by native hooks need review.
 */
export declare function registerV2TransportRedaction(session: SessionHooks, redactor: Pick<SecretRedactor, "redactMutableValueAsync">): Promise<() => Promise<void>>;

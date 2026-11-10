import type { SecretRedactor } from "../hooks/shared/secret-redaction.js";
import type { Registration, ToolHooks } from "./types.js";
type ToolErrorFactory = (message: string, cause?: unknown) => unknown;
type TrustedPermissionDeclineFactory = () => unknown;
/**
 * Experimental: both factories must come from trusted host capabilities.
 * The decline factory is sampled before registration and must not derive its
 * result from a tool error. A matching tag cannot authenticate a host type.
 */
export declare function registerV2ToolOutputRedaction(tool: ToolHooks, redactor: Pick<SecretRedactor, "redactMutableValueAsync">, createToolError: ToolErrorFactory, runtimeVersion: string, createTrustedDecline: TrustedPermissionDeclineFactory): Promise<() => Promise<void>>;
type InterruptEvent = {
    sessionID: unknown;
    status: unknown;
    error?: unknown;
    result?: unknown;
};
type GuardEvent = {
    sessionID: unknown;
};
type GuardKind = "context" | "compaction" | "generate" | "title" | "http.request" | "experimental.ws.send";
interface InterruptToolHooks {
    hook(name: "execute.after", callback: (event: InterruptEvent) => Promise<void>): Promise<Registration>;
}
interface InterruptSessionHooks {
    hook(name: GuardKind, callback: (event: GuardEvent) => Promise<void>): Promise<Registration>;
    interrupt(input: {
        sessionID: string;
        resume: false;
    }): Promise<{
        interrupted: boolean;
    }>;
    wait(input: {
        sessionID: string;
    }): Promise<unknown>;
}
/**
 * Experimental alternative to copying a host decline prototype. It is not a
 * complete provider boundary and must not be configured as a standalone guard.
 */
export declare function registerV2InterruptingToolOutputRedaction(session: InterruptSessionHooks, tool: InterruptToolHooks, redactor: Pick<SecretRedactor, "redactMutableValueAsync">, createToolError: ToolErrorFactory, runtimeVersion: string): Promise<() => Promise<void>>;
export {};

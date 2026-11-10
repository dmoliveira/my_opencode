import type { SecretRedactor } from "../hooks/shared/secret-redaction.js";
import type { ToolHooks } from "./types.js";
type ToolErrorFactory = (message: string, cause?: unknown) => unknown;
type TrustedPermissionDeclineFactory = () => unknown;
/**
 * Experimental: both factories must come from trusted host capabilities.
 * The decline factory is sampled before registration and must not derive its
 * result from a tool error. A matching tag cannot authenticate a host type.
 */
export declare function registerV2ToolOutputRedaction(tool: ToolHooks, redactor: Pick<SecretRedactor, "redactMutableValueAsync">, createToolError: ToolErrorFactory, runtimeVersion: string, createTrustedDecline: TrustedPermissionDeclineFactory): Promise<() => Promise<void>>;
export {};

import type { SecretRedactor } from "../hooks/shared/secret-redaction.js";
import type { ToolHooks } from "./types.js";
/** Redact successful V2 tool results before they are returned to the session. */
export declare function registerV2ToolOutputRedaction(tool: ToolHooks, redactor: Pick<SecretRedactor, "redactMutableValueAsync">): Promise<() => Promise<void>>;

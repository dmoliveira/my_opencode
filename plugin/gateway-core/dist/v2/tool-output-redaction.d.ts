import type { SecretRedactor } from "../hooks/shared/secret-redaction.js";
import type { ToolHooks } from "./types.js";
type ToolErrorFactory = (message: string, cause?: unknown) => unknown;
/** Experimental output adapter. The factory must create the host's V2 Tool.Error. */
export declare function registerV2ToolOutputRedaction(tool: ToolHooks, redactor: Pick<SecretRedactor, "redactMutableValueAsync">, createToolError: ToolErrorFactory, runtimeVersion: string): Promise<() => Promise<void>>;
export {};
